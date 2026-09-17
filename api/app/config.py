"""Environment-driven configuration."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (parent of api/) or api/ itself, if present.
_ROOT = Path(__file__).resolve().parents[2]
for candidate in (_ROOT / ".env", _ROOT / "api" / ".env"):
    if candidate.exists():
        load_dotenv(candidate)
        break
for _var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
    if _var in os.environ and not os.environ[_var].strip():
        del os.environ[_var]


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# On Vercel there is no git binary and no clone, so the defaults flip to the GitHub-backed
# modes. Explicit env vars always win.
_ON_VERCEL = bool(os.environ.get("VERCEL"))


class Config:
    DATABASE_URL: str = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or "sqlite:///./data/dev.db"
    # Credentials are resolved by the Anthropic SDK itself (API key env var, bearer token,
    # or an `ant auth login` OAuth profile). Nothing is read here on purpose.
    # local   = git clone + background thread (default for `make dev`)
    # chunked = GitHub tarball + one time-boxed step per HTTP call (Vercel)
    # off     = view only
    GENERATION_MODE: str = os.environ.get("GENERATION_MODE") or (
        "chunked" if _ON_VERCEL else ("local" if _bool(os.environ.get("GENERATION_ENABLED"), True) else "off")
    )
    GENERATION_ENABLED: bool = GENERATION_MODE != "off"
    STEP_BUDGET_S: float = float(os.environ.get("STEP_BUDGET_S", "150"))  # chunked mode: seconds of work per HTTP call
    # Public demo: no new repos and no new tags (chat, overview and summaries stay on, rate limited)
    DEMO_MODE: bool = _bool(os.environ.get("DEMO_MODE"), False)
    # Per-IP leaky bucket for model-calling endpoints: burst LLM_RATE_CAPACITY, then one per LLM_RATE_LEAK_SECONDS
    RATE_LIMIT_ENABLED: bool = _bool(os.environ.get("RATE_LIMIT_ENABLED"), True)
    LLM_RATE_CAPACITY: float = float(os.environ.get("LLM_RATE_CAPACITY", "10"))
    LLM_RATE_LEAK_SECONDS: float = float(os.environ.get("LLM_RATE_LEAK_SECONDS", "20"))
    # Optional token for private repos (clone, tarball, raw files, tags API)
    GITHUB_TOKEN: str | None = os.environ.get("GITHUB_TOKEN") or None
    REPO_CACHE_DIR: Path = Path(os.environ.get("REPO_CACHE_DIR", "./data/repos")).resolve()
    FILE_SOURCE: str = os.environ.get("FILE_SOURCE") or ("github" if _ON_VERCEL else "local")  # local | github
    MODEL: str = os.environ.get("ARCH_MODEL", "claude-sonnet-5")
    TAGS_ON_LOAD: int = int(os.environ.get("TAGS_ON_LOAD", "3"))
    MAX_FILE_BYTES: int = int(os.environ.get("MAX_FILE_BYTES", str(100 * 1024)))
    FANOUT_WORKERS: int = int(os.environ.get("FANOUT_WORKERS", "4"))

    @classmethod
    def is_sqlite(cls) -> bool:
        return cls.DATABASE_URL.startswith("sqlite")
