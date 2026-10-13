"""Background download jobs.

A job downloads and merges a video into its own temp directory while the client polls its
status. Once ready, the client fetches the file with a normal GET, so the browser's own
download manager streams it to disk — large files never sit in browser memory.
"""

import logging
import secrets
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import video
from .config import settings

logger = logging.getLogger("tube.jobs")

ACTIVE = {"queued", "downloading", "merging"}


@dataclass
class Job:
    id: str
    url: str
    resolution: int
    workdir: Path
    status: str = "queued"  # queued | downloading | merging | ready | error | cancelled
    downloaded: int = 0
    total: int | None = None
    error: str | None = None
    path: Path | None = None
    filename: str | None = None
    cancel_requested: bool = False
    updated: float = field(default_factory=time.monotonic)

    def public(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "downloaded": self.downloaded,
            "total": self.total,
            "error": self.error,
            "filename": self.filename,
            "filesize": self.path.stat().st_size if self.path and self.path.exists() else None,
        }


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def _run(job: Job) -> None:
    def on_progress(phase: str, downloaded: int, total: int | None) -> None:
        job.status, job.downloaded, job.total, job.updated = phase, downloaded, total, time.monotonic()

    try:
        job.status = "downloading"
        path, filename = video.download(
            job.url, job.resolution, job.workdir, on_progress, lambda: job.cancel_requested
        )
        job.path, job.filename, job.status = path, filename, "ready"
    except video.VideoError as exc:
        job.status = "cancelled" if job.cancel_requested else "error"
        job.error = exc.message
        shutil.rmtree(job.workdir, ignore_errors=True)
    except Exception:
        logger.exception("Job %s failed", job.id)
        job.status, job.error = "error", "Something went wrong. Please try again later."
        shutil.rmtree(job.workdir, ignore_errors=True)
    finally:
        job.updated = time.monotonic()


def start(url: str, resolution: int) -> Job:
    video.canonical_url(url)  # fail fast on bad input
    if resolution not in video.SUPPORTED_RESOLUTIONS:
        raise video.VideoError("Unsupported resolution.", 422)

    with _lock:
        if sum(j.status in ACTIVE for j in _jobs.values()) >= settings.max_concurrent_downloads:
            raise video.VideoError("The server is busy. Please try again in a minute.", 503)
        job = Job(
            id=secrets.token_urlsafe(16),
            url=url,
            resolution=resolution,
            workdir=Path(tempfile.mkdtemp(prefix="tube-", dir=settings.temp_dir)),
        )
        _jobs[job.id] = job

    threading.Thread(target=_run, args=(job,), name=f"job-{job.id[:6]}", daemon=True).start()
    return job


def get(job_id: str) -> Job:
    job = _jobs.get(job_id)
    if not job:
        raise video.VideoError("This download has expired. Please start it again.", 404)
    return job


def cancel(job_id: str) -> None:
    job = get(job_id)
    if job.status in ACTIVE:
        job.cancel_requested = True
    else:
        remove(job_id)


def remove(job_id: str) -> None:
    with _lock:
        job = _jobs.pop(job_id, None)
    if job:
        shutil.rmtree(job.workdir, ignore_errors=True)


def sweep() -> None:
    """Delete finished jobs nobody collected, and failed/cancelled jobs after a short grace period."""
    now = time.monotonic()
    for job in list(_jobs.values()):
        age = now - job.updated
        if (job.status == "ready" and age > settings.job_ttl) or (
            job.status in {"error", "cancelled"} and age > 300
        ):
            logger.info("Removing expired job %s (%s)", job.id, job.status)
            remove(job.id)


def remove_stale_dirs() -> None:
    """Remove temp folders left behind by a previous run (e.g. after a crash)."""
    base = Path(settings.temp_dir or tempfile.gettempdir())
    for d in base.glob("tube-*"):
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
