"""YouTube metadata extraction and downloading via yt-dlp."""

import logging
import re
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yt_dlp
from yt_dlp.utils import DownloadCancelled, DownloadError

from .config import settings

logger = logging.getLogger("tube.video")

ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}
SUPPORTED_RESOLUTIONS = (360, 480, 720, 1080)
DOWNLOAD_ATTEMPTS = 3
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
PATH_ID_RE = re.compile(r"^/(?:shorts|embed|live|v)/([A-Za-z0-9_-]{11})(?:/|$)")
QUALITY_RE = re.compile(r"(\d{3,4})p")


class VideoError(Exception):
    """An error whose message is safe to show to the client."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# --------------------------------------------------------------------------- URL handling


def canonical_url(raw: str) -> str:
    """Validate a YouTube URL and return the canonical watch URL for its video ID.

    Rebuilding the URL from the ID drops playlist/radio parameters and guarantees the
    request only ever goes to youtube.com.
    """
    raw = (raw or "").strip()
    if not raw or len(raw) > 2048:
        raise VideoError("Please enter a valid YouTube video URL.")
    if "://" not in raw:
        raw = "https://" + raw

    try:
        parsed = urlparse(raw)
    except ValueError:
        raise VideoError("Please enter a valid YouTube video URL.")

    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in ALLOWED_HOSTS:
        raise VideoError("Only YouTube links (youtube.com or youtu.be) are supported.")

    video_id = None
    if host.endswith("youtu.be"):
        video_id = parsed.path.lstrip("/").split("/")[0]
    elif parsed.path == "/watch":
        video_id = (parse_qs(parsed.query).get("v") or [""])[0]
    elif match := PATH_ID_RE.match(parsed.path):
        video_id = match.group(1)

    if not video_id or not VIDEO_ID_RE.match(video_id):
        raise VideoError("That doesn't look like a YouTube video link. Playlists and channels aren't supported.")
    return f"https://www.youtube.com/watch?v={video_id}"


# --------------------------------------------------------------------------- yt-dlp helpers


class _Logger:
    """Route yt-dlp output to our logger instead of stdout."""

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        logger.debug("yt-dlp: %s", msg)

    def error(self, msg):
        logger.warning("yt-dlp: %s", msg)


def _base_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "noprogress": True,
        "socket_timeout": 20,
        "logger": _Logger(),
        "js_runtimes": {name: {} for name in settings.js_runtimes},
        "cachedir": False,
    }
    if settings.ffmpeg_location:
        opts["ffmpeg_location"] = settings.ffmpeg_location
    return opts


def _friendly_error(exc: Exception) -> VideoError:
    text = str(exc).lower()
    rules = [
        (("private video",), "This video is private.", 403),
        (("confirm your age", "age-restricted", "inappropriate for some users"),
         "This video is age-restricted and can't be downloaded.", 403),
        (("members-only", "join this channel", "members only"),
         "This video is only available to channel members.", 403),
        (("drm",), "This video is DRM-protected and isn't supported.", 403),
        (("not a bot", "http error 429", "too many requests"),
         "YouTube is temporarily limiting requests from this server. Please try again later.", 503),
        (("copyright",), "This video is unavailable due to a copyright claim.", 404),
        (("not available in your country", "geo restrict", "blocked it in your country"),
         "This video isn't available in the server's region.", 403),
        (("premieres in", "live event will begin", "this live event"),
         "This video hasn't been released yet.", 404),
        (("requested format is not available", "no video formats"),
         "The selected format isn't available for this video.", 422),
        (("unavailable", "has been removed", "account associated", "terminated",
          "does not exist", "not available", "http error 404"),
         "This video is unavailable.", 404),
    ]
    for needles, message, status in rules:
        if any(n in text for n in needles):
            return VideoError(message, status)
    logger.error("Unhandled yt-dlp error: %s", exc)
    return VideoError("We couldn't process this video. Please try again later.", 502)


def _extract(ydl: yt_dlp.YoutubeDL, url: str) -> dict:
    try:
        info = ydl.extract_info(url, download=False)
    except DownloadError as exc:
        raise _friendly_error(exc)

    if not info or info.get("_type", "video") != "video":
        raise VideoError("That link doesn't point to a single video.")
    if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming", "post_live"}:
        raise VideoError("Live streams and upcoming premieres aren't supported.", 422)
    return info


def _quality(fmt: dict) -> int | None:
    """YouTube's quality label (e.g. 1080 for '1080p'), which follows the shorter side."""
    if match := QUALITY_RE.search(fmt.get("format_note") or ""):
        return int(match.group(1))
    w, h = fmt.get("width"), fmt.get("height")
    if w and h:
        return min(w, h)
    return h


def _size(fmt: dict | None) -> int | None:
    if not fmt:
        return None
    return fmt.get("filesize") or fmt.get("filesize_approx")


def _is_video(fmt: dict) -> bool:
    return fmt.get("vcodec") not in (None, "none") and bool(fmt.get("height"))


def _is_audio_only(fmt: dict) -> bool:
    return fmt.get("acodec") not in (None, "none") and fmt.get("vcodec") in (None, "none")


def _is_drm(fmt: dict) -> bool:
    return bool(fmt.get("has_drm"))


def _pick_formats(info: dict, resolution: int) -> tuple[dict, dict | None]:
    """Choose the best video stream at `resolution` plus an audio stream to merge with.

    Prefers H.264 video and AAC (m4a) audio so the merged MP4 plays everywhere.
    """
    formats = [f for f in info.get("formats") or [] if not _is_drm(f)]
    videos = [
        f for f in formats
        if _is_video(f) and _quality(f) == resolution and not (f.get("protocol") or "").startswith("m3u8")
    ]
    if not videos:
        raise VideoError(f"{resolution}p isn't available for this video.", 422)

    def video_rank(f):
        return (
            (f.get("vcodec") or "").startswith("avc1"),
            f.get("ext") == "mp4",
            f.get("fps") or 0,
            f.get("tbr") or 0,
        )

    video = max(videos, key=video_rank)
    if video.get("acodec") not in (None, "none"):
        return video, None  # progressive stream already contains audio

    audios = [f for f in formats if _is_audio_only(f) and not (f.get("protocol") or "").startswith("m3u8")]
    if not audios:
        raise VideoError("No audio stream is available for this video.", 422)

    def audio_rank(f):
        return (
            f.get("ext") == "m4a",
            "drc" not in (f.get("format_id") or ""),
            "original" in (f.get("format_note") or "").lower() or (f.get("language_preference") or 0) > 0,
            f.get("abr") or f.get("tbr") or 0,
        )

    return video, max(audios, key=audio_rank)


# --------------------------------------------------------------------------- public API


def get_info(raw_url: str) -> dict:
    url = canonical_url(raw_url)
    with yt_dlp.YoutubeDL({**_base_opts(), "skip_download": True}) as ydl:
        info = _extract(ydl, url)

    resolutions = []
    for res in SUPPORTED_RESOLUTIONS:
        try:
            video, audio = _pick_formats(info, res)
        except VideoError:
            continue
        v_size, a_size = _size(video), _size(audio)
        est = (v_size + (a_size or 0)) if v_size else None
        resolutions.append({
            "height": res,
            "label": {720: "720p HD", 1080: "1080p Full HD"}.get(res, f"{res}p"),
            "filesize": est,
            "too_large": bool(est and est > settings.max_filesize_bytes),
        })

    if not resolutions:
        raise VideoError("No supported resolutions (360p–1080p) are available for this video.", 422)

    return {
        "id": info.get("id"),
        "url": url,
        "title": info.get("title") or "Untitled video",
        "uploader": info.get("uploader") or info.get("channel"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "resolutions": resolutions,
        "max_filesize_label": limit_text(),
    }


ProgressCallback = Callable[[str, int, int | None], None]


def limit_text() -> str:
    mb = settings.max_filesize_mb
    return f"{mb / 1024:g} GB" if mb >= 1024 else f"{mb} MB"


def download(
    raw_url: str,
    resolution: int,
    workdir: Path,
    on_progress: ProgressCallback = lambda *_: None,
    is_cancelled: Callable[[], bool] = lambda: False,
) -> tuple[Path, str]:
    """Download `resolution` into `workdir`. Returns (file path, suggested filename).

    `on_progress(phase, downloaded_bytes, total_bytes)` is called with phase "downloading" or "merging".
    """
    if resolution not in SUPPORTED_RESOLUTIONS:
        raise VideoError("Unsupported resolution.", 422)

    url = canonical_url(raw_url)
    deadline = time.monotonic() + settings.download_timeout
    state: dict = {"estimate": None, "files": {}}

    def guard(d: dict) -> None:
        if is_cancelled():
            raise DownloadCancelled("cancelled")
        if time.monotonic() > deadline:
            raise DownloadCancelled("timeout")
        files = state["files"]
        files[d.get("filename", "")] = (
            d.get("downloaded_bytes") or 0,
            d.get("total_bytes") or d.get("total_bytes_estimate") or 0,
        )
        downloaded = sum(done for done, _ in files.values())
        if downloaded > settings.max_filesize_bytes:
            raise DownloadCancelled("too_large")
        on_progress("downloading", downloaded, state["estimate"] or sum(t for _, t in files.values()) or None)

    def on_postprocess(d: dict) -> None:
        if d.get("postprocessor") == "Merger" and d.get("status") == "started":
            downloaded = sum(done for done, _ in state["files"].values())
            on_progress("merging", downloaded, downloaded)

    opts = {
        **_base_opts(),
        "outtmpl": str(workdir / "%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "max_filesize": settings.max_filesize_bytes,
        "progress_hooks": [guard],
        "postprocessor_hooks": [on_postprocess],
        "overwrites": True,
        "continuedl": False,
        "retries": 3,
        "fragment_retries": 3,
    }

    try:
        for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
            try:
                info = _download_once(url, resolution, opts, workdir, state)
                break
            except DownloadError as exc:
                # googlevideo intermittently rejects a stream URL; fresh URLs usually work.
                if "http error 403" not in str(exc).lower() or attempt == DOWNLOAD_ATTEMPTS:
                    raise
                logger.info("Got HTTP 403 for %s, retrying with fresh URLs", url)
                state["files"].clear()
                for leftover in workdir.iterdir():
                    leftover.unlink(missing_ok=True)
    except DownloadCancelled as exc:
        if "cancelled" in str(exc):
            raise VideoError("Download cancelled.", 499)
        if "too_large" in str(exc):
            raise VideoError(f"The file exceeds the {limit_text()} limit. Try a lower resolution.", 413)
        raise VideoError("The download took too long and was stopped. Try a lower resolution.", 504)
    except DownloadError as exc:
        if "ffmpeg" in str(exc).lower():
            logger.error("FFmpeg problem: %s", exc)
            raise VideoError("The server couldn't process this video. Please try again later.", 500)
        raise _friendly_error(exc)

    files = [p for p in workdir.iterdir() if p.is_file() and p.suffix in {".mp4", ".mkv", ".webm"}]
    if not files:
        # yt-dlp skips (without error) files that exceed max_filesize.
        raise VideoError(f"The file exceeds the {limit_text()} limit. Try a lower resolution.", 413)
    path = max(files, key=lambda p: p.stat().st_size)
    if path.stat().st_size > settings.max_filesize_bytes:
        raise VideoError(f"The file exceeds the {limit_text()} limit. Try a lower resolution.", 413)

    return path, f"{_safe_filename(info.get('title') or info['id'])} [{resolution}p]{path.suffix}"


def _download_once(url: str, resolution: int, opts: dict, workdir: Path, state: dict) -> dict:
    # Extract and download with one instance: the media URLs are tied to its session.
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = _extract(ydl, url)
        video, audio = _pick_formats(info, resolution)

        estimate = (_size(video) or 0) + (_size(audio) or 0)
        if estimate > settings.max_filesize_bytes:
            raise VideoError(
                f"This video is too large at {resolution}p (limit {limit_text()}). Try a lower resolution.",
                413,
            )
        # The separate streams and the merged file exist side by side for a moment.
        if estimate and shutil.disk_usage(workdir).free < estimate * 2.2 + 200 * 1024 * 1024:
            logger.error("Not enough disk space for %s (needs ~%d MB)", url, estimate * 2.2 // 2**20)
            raise VideoError("The server doesn't have enough free space for this video right now.", 507)
        state["estimate"] = estimate or None

        ydl.format_selector = ydl.build_format_selector(
            video["format_id"] + (f"+{audio['format_id']}" if audio else "")
        )
        ydl.process_ie_result(info, download=True)
    return info


def _safe_filename(title: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", title)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name or "video")[:150]
