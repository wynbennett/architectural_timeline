"""Prompt templates (Jinja2, under llm/prompts/*.md.j2), compiled once and cached."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

PROMPTS_DIR = Path(__file__).parent / "prompts"
PROMPT_VERSION = "v2"  # bump when prompt *text* changes; reuse across tags only happens within one version

_env = Environment(
    loader=FileSystemLoader(str(PROMPTS_DIR)),
    autoescape=False,          # prompts are plain text, never HTML
    undefined=StrictUndefined, # a missing variable is a bug, not an empty string
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
    auto_reload=False,         # templates are compiled once per process and cached by the Environment
)


def render_prompt(template: str, /, **context: object) -> str:
    """Render llm/prompts/<template>.md.j2 with the given variables (positional-only so a
    variable called `name` or `template` in the prompt never collides)."""
    return _env.get_template(f"{template}.md.j2").render(**context)


@lru_cache(maxsize=None)
def system_prompt() -> str:
    """The shared system prompt for every generation call (static, so cached as a string)."""
    return render_prompt("system")
