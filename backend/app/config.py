"""Application settings, read from environment variables (and an optional .env file)."""

import os
import shutil
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _list(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_ffmpeg() -> str | None:
    """Locate FFmpeg: explicit setting, then PATH, then the imageio-ffmpeg bundled binary."""
    explicit = os.getenv("FFMPEG_LOCATION", "").strip()
    if explicit:
        return explicit
    if shutil.which("ffmpeg"):
        return None  # yt-dlp finds it on PATH by itself
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


@dataclass(frozen=True)
class Settings:
    allowed_origins: list[str] = field(
        default_factory=lambda: _list("ALLOWED_ORIGINS", "http://localhost:3000")
    )
    max_filesize_mb: int = _int("MAX_FILESIZE_MB", 10240)
    info_timeout: int = _int("INFO_TIMEOUT_SECONDS", 30)
    download_timeout: int = _int("DOWNLOAD_TIMEOUT_SECONDS", 3600)
    rate_limit_info: int = _int("RATE_LIMIT_INFO_PER_MINUTE", 20)
    rate_limit_download: int = _int("RATE_LIMIT_DOWNLOAD_PER_MINUTE", 5)
    max_concurrent_downloads: int = _int("MAX_CONCURRENT_DOWNLOADS", 3)
    job_ttl: int = _int("JOB_TTL_SECONDS", 1800)
    trust_proxy: bool = _bool("TRUST_PROXY", False)
    js_runtimes: list[str] = field(default_factory=lambda: _list("JS_RUNTIMES", "deno,node"))
    temp_dir: str | None = os.getenv("TEMP_DIR") or None
    ffmpeg_location: str | None = field(default_factory=_resolve_ffmpeg)

    @property
    def max_filesize_bytes(self) -> int:
        return self.max_filesize_mb * 1024 * 1024


settings = Settings()
