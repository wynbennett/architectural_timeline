"""Streaming chat about a generated graph, with file-reading tools."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Iterator

from ..config import Config
from ..ingest.filesource import get_file_source
from ..models import Tag
from .client import fallback_kwargs, get_client
from .generate import tier3_key
from .prompts import render_prompt

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 8
MAX_READ_LINES = 400

TOOLS = [
    {
        "name": "read_file",
        "description": "Read a source file at the current tag. Returns numbered lines. Use start_line/end_line to read a slice of a large file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "exact repository path"},
                "start_line": {"type": "integer", "description": "1-based, optional"},
                "end_line": {"type": "integer", "description": "1-based inclusive, optional"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "list_files",
        "description": "List repository file paths at the current tag, optionally filtered by a path prefix or substring.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "prefix or substring; empty for everything"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


@dataclass
class ChatContext:
    owner: str
    name: str
    tag: str
    sha: str
    architecture: str
    viewing: str
    paths: list[str] = field(default_factory=list)
    comparison: str | None = None

    @classmethod
    def from_tag(cls, tag: Tag, *, tier: int, system_id: str | None, module_id: str | None, selected_node: str | None, open_file: str | None) -> "ChatContext":
        g = tag.graph
        arch: dict = {"system_level": g.tier1}
        if g.overview:
            arch["written_overview"] = g.overview
        if system_id and system_id in g.tier2:
            arch["modules_of_selected_system"] = {system_id: g.tier2[system_id]}
        if system_id and module_id:
            key = tier3_key(system_id, module_id)
            if key in g.tier3:
                arch["snippets_of_selected_module"] = {key: g.tier3[key]}
        crumbs = ["System"]
        if system_id:
            crumbs.append(system_id)
        if module_id:
            crumbs.append(module_id)
        viewing = f"tag {tag.name}; tier {tier}; breadcrumb {' > '.join(crumbs)}"
        if selected_node:
            viewing += f"; selected node {selected_node}"
        if open_file:
            viewing += f"; open file {open_file}"
        return cls(
            owner=tag.repo.owner, name=tag.repo.name, tag=tag.name, sha=tag.commit_sha,
            architecture=json.dumps(arch, indent=1), viewing=viewing,
            paths=[f.path for f in tag.files],
        )

    def system_prompt(self) -> str:
        text = render_prompt("chat", owner=self.owner, name=self.name, tag=self.tag, architecture=self.architecture, viewing=self.viewing)
        if self.comparison:
            text += "\n\n<comparison>\n" + self.comparison + "\n</comparison>"
        return text


def _run_tool(ctx: ChatContext, name: str, args: dict) -> tuple[str, bool]:
    if name == "list_files":
        q = (args.get("query") or "").strip("/")
        hits = [p for p in ctx.paths if not q or p.startswith(q) or q in p]
        if not hits:
            return "no matching files", False
        more = f"\n... {len(hits) - 200} more" if len(hits) > 200 else ""
        return "\n".join(hits[:200]) + more, False
    if name == "read_file":
        path = str(args.get("path", "")).strip("/")
        content = get_file_source().read(ctx.owner, ctx.name, ctx.sha, path, allowed=set(ctx.paths))
        if content is None:
            return f"file not found at this tag: {path}", True
        lines = content.splitlines()
        start = max(1, int(args.get("start_line") or 1))
        end = min(len(lines), int(args.get("end_line") or (start + MAX_READ_LINES - 1)))
        end = min(end, start + MAX_READ_LINES - 1)
        body = "\n".join(f"{i:5d}  {lines[i - 1]}" for i in range(start, end + 1))
        if end < len(lines):
            body += f"\n... ({len(lines) - end} more lines; total {len(lines)})"
        return body, False
    return f"unknown tool {name}", True


def _clean_history(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            out.append({"role": role, "content": content})
    if not out or out[0]["role"] != "user":
        raise ValueError("conversation must start with a user message")
    return out


def stream_chat(ctx: ChatContext, messages: list[dict]) -> Iterator[dict]:
    """Yields events: {type: text, text} | {type: tool_use, name, input} | {type: tool_result, name, ok}."""
    client = get_client()
    history = _clean_history(messages)
    system = [{"type": "text", "text": ctx.system_prompt(), "cache_control": {"type": "ephemeral"}}]

    for _round in range(MAX_TOOL_ROUNDS + 1):
        with client.beta.messages.stream(
            model=Config.MODEL,
            max_tokens=16000,
            system=system,
            messages=history,
            tools=TOOLS,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            **fallback_kwargs(),
        ) as stream:
            for event in stream:
                if event.type == "text":
                    yield {"type": "text", "text": event.text}
            msg = stream.get_final_message()

        if msg.stop_reason == "refusal":
            yield {"type": "error", "message": "the model declined to answer this question"}
            return
        tool_uses = [b for b in msg.content if b.type == "tool_use"]
        if not tool_uses or msg.stop_reason == "max_tokens":
            return

        history.append({"role": "assistant", "content": msg.content})
        results = []
        for block in tool_uses:
            args = block.input if isinstance(block.input, dict) else {}
            yield {"type": "tool_use", "name": block.name, "input": args}
            text, is_error = _run_tool(ctx, block.name, args)
            yield {"type": "tool_result", "name": block.name, "ok": not is_error}
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": text, "is_error": is_error})
        history.append({"role": "user", "content": results})
    yield {"type": "error", "message": "stopped after too many tool calls"}
