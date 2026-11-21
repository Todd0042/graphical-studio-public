"""Web wrapper settings, read from web/.env (KEY=VALUE) with process env taking precedence."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import addons

WEB_DIR = Path(__file__).resolve().parent
ROOT_DIR = WEB_DIR.parent
ENV_FILE = Path(os.environ.get("GS_WEB_ENV_FILE", str(WEB_DIR / ".env")))


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            values[key.strip()] = val.strip().strip('"').strip("'")
    return values


@dataclass(frozen=True)
class Settings:
    allowed_user: str  # GitHub login allowed in
    sso_url: str  # Dev SSO sign-in hand-off URL
    sso_site: str  # This site's id in dev-sso config
    sso_secret_path: Path
    session_secret: str
    session_ttl_seconds: int
    allowed_hosts: tuple[str, ...]
    max_queued_jobs: int
    max_upload_bytes: int
    jobs_path: Path
    uploads_dir: Path

    @property
    def auth_configured(self) -> bool:
        return bool(self.allowed_user and self.sso_url and len(self.session_secret) >= 32 and self.sso_secret_path.is_file())


def load_settings() -> Settings:
    env_path = Path(os.environ.get("GS_WEB_ENV_FILE", str(ENV_FILE)))
    env = {**_load_env_file(env_path), **os.environ}
    priv = addons.REGISTRY.private_web_defaults
    hosts = env.get("GS_WEB_ALLOWED_HOSTS", priv.get("allowed_hosts", "127.0.0.1:8040,localhost:8040"))
    cache = ROOT_DIR / ".cache"
    return Settings(
        allowed_user=env.get("GS_WEB_ALLOWED_GITHUB_USER", priv.get("allowed_user", "")).lower(),
        sso_url=env.get("GS_WEB_SSO_URL", priv.get("sso_url", "")),
        sso_site=env.get("GS_WEB_SSO_SITE", priv.get("sso_site", "graphical-studio")),
        sso_secret_path=Path(env.get("DEV_SSO_SECRET", str(Path.home() / ".config" / "dev-sso" / "secret"))),
        session_secret=env.get("GS_WEB_SESSION_SECRET", ""),
        session_ttl_seconds=int(env.get("GS_WEB_SESSION_TTL", str(7 * 86400))),
        allowed_hosts=tuple(h.strip().lower() for h in hosts.split(",") if h.strip()),
        max_queued_jobs=int(env.get("GS_WEB_MAX_QUEUED", "20")),
        max_upload_bytes=int(env.get("GS_WEB_MAX_UPLOAD_MB", "15")) * 1024 * 1024,
        jobs_path=Path(env.get("GS_WEB_JOBS_PATH", str(cache / "web_jobs.json"))),
        uploads_dir=Path(env.get("GS_WEB_UPLOADS_DIR", str(cache / "web_uploads"))),
    )
