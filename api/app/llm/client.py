"""Anthropic client wrapper used by the generator and chat."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel

if TYPE_CHECKING:  # the SDK is imported lazily: it is the slowest import and not needed to serve graphs
    import anthropic

from ..config import Config

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


def fallback_kwargs() -> dict:
    """Server-side refusal fallbacks are an Opus 5 / Fable feature; skip them elsewhere."""
    if Config.MODEL.startswith(("claude-opus-5", "claude-fable")):
        return {"betas": [FALLBACK_BETA], "fallbacks": "default"}
    return {}

_client: "anthropic.Anthropic | None" = None


def _config_dir() -> Path:
    env = os.environ.get("ANTHROPIC_CONFIG_DIR")
    if env:
        return Path(env).expanduser()
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "Anthropic"
    return Path.home() / ".config" / "anthropic"


def active_profile() -> str | None:
    """Name of the on-disk OAuth profile the SDK would use, or None if there is none."""
    cfg = _config_dir()
    name = os.environ.get("ANTHROPIC_PROFILE")
    if not name:
        marker = cfg / "active_config"
        name = marker.read_text().strip() if marker.exists() else "default"
    if (cfg / "credentials" / f"{name}.json").exists() or (cfg / "configs" / f"{name}.json").exists():
        return name
    return None


def auth_source() -> str:
    """Human-readable description of the credential source, mirroring the SDK's precedence."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "api key (ANTHROPIC_API_KEY)"
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "bearer token (ANTHROPIC_AUTH_TOKEN)"
    if os.environ.get("ANTHROPIC_IDENTITY_TOKEN") or os.environ.get("ANTHROPIC_IDENTITY_TOKEN_FILE"):
        return "workload identity federation"
    profile = active_profile()
    if profile:
        return f"oauth profile '{profile}' (ant auth login)"
    return "none"


def get_client() -> "anthropic.Anthropic":
    """Zero-arg client: the SDK resolves ANTHROPIC_API_KEY, then ANTHROPIC_AUTH_TOKEN,
    then an `ant auth login` OAuth profile (ANTHROPIC_PROFILE or the active/default one)."""
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(max_retries=3)
    return _client


class LLMRefusal(RuntimeError):
    pass


def structured_call(system: str, user: str, output_type: type[T], *, max_tokens: int = 32000, effort: str = "high") -> T:
    """One streamed request that must come back as `output_type` JSON."""
    client = get_client()
    with client.beta.messages.stream(
        model=Config.MODEL,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        output_format=output_type,
        **fallback_kwargs(),
    ) as stream:
        msg = stream.get_final_message()

    u = msg.usage
    log.info(
        "%s: in=%s cache_read=%s cache_write=%s out=%s stop=%s",
        output_type.__name__, u.input_tokens, getattr(u, "cache_read_input_tokens", None),
        getattr(u, "cache_creation_input_tokens", None), u.output_tokens, msg.stop_reason,
    )
    if msg.stop_reason == "refusal":
        details = getattr(msg, "stop_details", None)
        raise LLMRefusal(f"model refused: {getattr(details, 'category', None)}")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("model output truncated at max_tokens")
    parsed = msg.parsed_output
    if parsed is None:
        raise RuntimeError("model returned no parsable structured output")
    return parsed
