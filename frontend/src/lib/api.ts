export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export type Resolution = {
  height: number;
  label: string;
  filesize: number | null;
  too_large: boolean;
};

export type VideoInfo = {
  id: string;
  url: string;
  title: string;
  uploader: string | null;
  duration: number | null;
  thumbnail: string | null;
  resolutions: Resolution[];
  max_filesize_label: string;
};

export class ApiError extends Error {}

const YOUTUBE_URL = /^(https?:\/\/)?((www|m)\.)?(youtube\.com|youtu\.be)\/\S+$/i;

export function looksLikeYouTubeUrl(value: string): boolean {
  return YOUTUBE_URL.test(value.trim());
}

async function errorFrom(res: Response): Promise<ApiError> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return new ApiError(body.detail);
  } catch {
    // fall through to a generic message
  }
  if (res.status === 429) return new ApiError("Too many requests. Please wait a moment and try again.");
  return new ApiError("Something went wrong. Please try again later.");
}

function networkError(err: unknown): Error {
  if (err instanceof DOMException && err.name === "AbortError") return err;
  if (err instanceof DOMException && err.name === "TimeoutError") {
    return new ApiError("The request timed out. Please try again.");
  }
  if (err instanceof ApiError) return err;
  return new ApiError("Can't reach the server. Check your connection and try again.");
}

export async function fetchVideoInfo(url: string): Promise<VideoInfo> {
  try {
    const res = await fetch(`${API_URL}/api/video/info`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
      signal: AbortSignal.timeout(60_000),
    });
    if (!res.ok) throw await errorFrom(res);
    return (await res.json()) as VideoInfo;
  } catch (err) {
    throw networkError(err);
  }
}

export type DownloadProgress = {
  phase: "queued" | "downloading" | "merging";
  downloaded: number;
  total: number | null;
};

type Job = {
  id: string;
  status: "queued" | "downloading" | "merging" | "ready" | "error" | "cancelled";
  downloaded: number;
  total: number | null;
  error: string | null;
  filename: string | null;
  filesize: number | null;
};

const POLL_INTERVAL_MS = 1000;

async function jobRequest(path: string, init?: RequestInit): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/video/download${path}`, init);
  } catch (err) {
    throw networkError(err);
  }
  if (!res.ok) throw await errorFrom(res);
  return res;
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(new DOMException("Aborted", "AbortError"));
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

/**
 * Have the server prepare the file (reporting progress while it downloads and merges),
 * then hand it to the browser's download manager. The file is streamed straight to disk by
 * the browser, so even multi-GB videos never sit in page memory.
 */
export async function downloadVideo(
  url: string,
  resolution: number,
  onProgress: (p: DownloadProgress) => void,
  signal: AbortSignal,
): Promise<{ filename: string; filesize: number | null }> {
  onProgress({ phase: "queued", downloaded: 0, total: null });
  let job: Job = await (
    await jobRequest("", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, resolution }),
      signal,
    })
  ).json();

  const cancelOnServer = () => {
    fetch(`${API_URL}/api/video/download/${job.id}`, { method: "DELETE", keepalive: true }).catch(() => {});
  };
  signal.addEventListener("abort", cancelOnServer, { once: true });

  try {
    while (job.status === "queued" || job.status === "downloading" || job.status === "merging") {
      onProgress({ phase: job.status, downloaded: job.downloaded, total: job.total });
      await sleep(POLL_INTERVAL_MS, signal);
      job = await (await jobRequest(`/${job.id}`, { signal })).json();
    }
  } finally {
    signal.removeEventListener("abort", cancelOnServer);
  }

  if (job.status !== "ready") {
    throw new ApiError(job.error ?? "The download failed. Please try again.");
  }

  // A plain navigation to an attachment URL starts a native download without leaving the page.
  const link = document.createElement("a");
  link.href = `${API_URL}/api/video/download/${job.id}/file`;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
  return { filename: job.filename ?? `video-${resolution}p.mp4`, filesize: job.filesize };
}
