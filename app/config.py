"""Server-side configuration.

All secrets are read from environment variables (optionally via a local `.env`
file) and never sent to the browser. See `.env.example` for every option.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


def _float(value: str | None, default: float) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except ValueError:
        return default


@dataclass
class Settings:
    tavily_api_key: str | None = None
    serpapi_api_key: str | None = None
    serpapi_location: str | None = None
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: str = "medium"
    anthropic_base_url: str = "https://api.anthropic.com"
    database_path: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "purchasing.db")
    fetch_pages: bool = True
    fetch_max_pages: int = 10
    fetch_timeout_s: float = 8.0
    fetch_max_bytes: int = 2_000_000
    respect_robots_txt: bool = True
    fetch_user_agent: str = (
        "Mozilla/5.0 (compatible; MidcontinentPurchasingResearch/0.1; "
        "+internal purchasing research tool)"
    )
    search_timeout_s: float = 25.0
    job_timeout_s: float = 300.0
    duplicate_window_hours: int = 12
    home_province: str = "ON"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


def load_settings(env_file: Path | None = None) -> Settings:
    """Build settings from the environment. `.env` never overrides real env vars."""
    load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)
    env = os.environ
    db_path = env.get("DATABASE_PATH")
    return Settings(
        tavily_api_key=env.get("TAVILY_API_KEY") or None,
        serpapi_api_key=env.get("SERPAPI_API_KEY") or None,
        serpapi_location=env.get("SERPAPI_LOCATION") or None,
        # The app only uses Claude when *its own* key is configured. We pass the
        # key and base URL explicitly so unrelated Anthropic credentials or
        # ANTHROPIC_BASE_URL values present on the machine are never picked up.
        anthropic_api_key=env.get("PI_ANTHROPIC_API_KEY") or env.get("ANTHROPIC_API_KEY") or None,
        anthropic_model=env.get("PI_ANTHROPIC_MODEL") or "claude-opus-5-5",
        anthropic_effort=env.get("PI_ANTHROPIC_EFFORT") or "medium",
        anthropic_base_url=env.get("PI_ANTHROPIC_BASE_URL") or "https://api.anthropic.com",
        database_path=Path(db_path) if db_path else PROJECT_ROOT / "data" / "purchasing.db",
        fetch_pages=_bool(env.get("FETCH_PAGES"), True),
        fetch_max_pages=_int(env.get("FETCH_MAX_PAGES"), 10),
        fetch_timeout_s=_float(env.get("FETCH_TIMEOUT_S"), 8.0),
        respect_robots_txt=_bool(env.get("RESPECT_ROBOTS_TXT"), True),
        search_timeout_s=_float(env.get("SEARCH_TIMEOUT_S"), 25.0),
        job_timeout_s=_float(env.get("JOB_TIMEOUT_S"), 300.0),
        duplicate_window_hours=_int(env.get("DUPLICATE_WINDOW_HOURS"), 12),
        home_province=(env.get("HOME_PROVINCE") or "ON").upper(),
    )
