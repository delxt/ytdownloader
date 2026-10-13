"""Tube Downloader API."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from . import jobs, video
from .config import settings
from .ratelimit import client_ip, download_limiter, info_limiter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("tube.api")


async def _sweep_forever():
    while True:
        await asyncio.sleep(60)
        jobs.sweep()


@asynccontextmanager
async def lifespan(_: FastAPI):
    jobs.remove_stale_dirs()
    sweeper = asyncio.create_task(_sweep_forever())
    yield
    sweeper.cancel()


app = FastAPI(title="Tube Downloader API", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
    expose_headers=["Content-Disposition", "Content-Length"],
)


class InfoRequest(BaseModel):
    url: str = Field(..., max_length=2048)


class DownloadRequest(BaseModel):
    url: str = Field(..., max_length=2048)
    resolution: int


# --------------------------------------------------------------------------- error handling


@app.exception_handler(video.VideoError)
async def video_error_handler(_: Request, exc: video.VideoError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, __: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": "Invalid request."})


@app.exception_handler(Exception)
async def unhandled_error_handler(_: Request, exc: Exception):
    logger.exception("Unhandled error", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong. Please try again later."})


# --------------------------------------------------------------------------- routes


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/video/info")
async def video_info(body: InfoRequest, request: Request):
    info_limiter.check(client_ip(request))
    try:
        return await asyncio.wait_for(run_in_threadpool(video.get_info, body.url), settings.info_timeout)
    except asyncio.TimeoutError:
        raise video.VideoError("YouTube took too long to respond. Please try again.", 504)


@app.post("/api/video/download", status_code=202)
async def start_download(body: DownloadRequest, request: Request):
    """Start preparing a download. Poll the returned job, then fetch its file."""
    download_limiter.check(client_ip(request))
    return jobs.start(body.url, body.resolution).public()


@app.get("/api/video/download/{job_id}")
async def download_status(job_id: str):
    return jobs.get(job_id).public()


@app.delete("/api/video/download/{job_id}", status_code=204)
async def cancel_download(job_id: str):
    jobs.cancel(job_id)


@app.get("/api/video/download/{job_id}/file")
async def download_file(job_id: str):
    job = jobs.get(job_id)
    if job.status != "ready" or not job.path or not job.path.exists():
        raise video.VideoError("This download isn't ready yet.", 409)
    return FileResponse(
        job.path,
        media_type="video/mp4" if job.path.suffix == ".mp4" else "application/octet-stream",
        filename=job.filename,
        # Delete as soon as the file has been sent; the sweeper handles interrupted transfers.
        background=BackgroundTask(jobs.remove, job.id),
    )
