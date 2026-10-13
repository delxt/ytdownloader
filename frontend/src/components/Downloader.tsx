"use client";

import { useRef, useState } from "react";
import {
  ApiError,
  downloadVideo,
  fetchVideoInfo,
  looksLikeYouTubeUrl,
  type DownloadProgress,
  type VideoInfo,
} from "@/lib/api";

type Status =
  | { kind: "idle" }
  | { kind: "fetching" }
  | { kind: "downloading"; progress: DownloadProgress }
  | { kind: "success"; message: string }
  | { kind: "error"; message: string };

function formatDuration(seconds: number | null): string | null {
  if (!seconds) return null;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return `${h ? `${h}:` : ""}${mm}:${String(s).padStart(2, "0")}`;
}

function formatBytes(bytes: number | null): string | null {
  if (!bytes) return null;
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(bytes < 10 * 1024 ** 2 ? 1 : 0)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

function messageOf(err: unknown): string {
  return err instanceof ApiError ? err.message : "Something went wrong. Please try again.";
}

function Spinner() {
  return (
    <span
      aria-hidden
      className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-r-transparent"
    />
  );
}

export default function Downloader() {
  const [url, setUrl] = useState("");
  const [info, setInfo] = useState<VideoInfo | null>(null);
  const [resolution, setResolution] = useState<number | null>(null);
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const abortRef = useRef<AbortController | null>(null);

  const busy = status.kind === "fetching" || status.kind === "downloading";

  async function handlePaste() {
    try {
      const text = (await navigator.clipboard.readText()).trim();
      if (!text) {
        setStatus({ kind: "error", message: "Your clipboard is empty." });
        return;
      }
      setUrl(text);
      setInfo(null);
      setStatus({ kind: "idle" });
    } catch {
      setStatus({
        kind: "error",
        message: "Clipboard access was blocked. Paste the link into the box with Ctrl+V (or long-press on mobile).",
      });
    }
  }

  async function handleFetch(e: React.FormEvent) {
    e.preventDefault();
    const value = url.trim();
    if (!value) {
      setStatus({ kind: "error", message: "Paste a YouTube video link first." });
      return;
    }
    if (!looksLikeYouTubeUrl(value)) {
      setStatus({ kind: "error", message: "Please enter a valid YouTube link (youtube.com or youtu.be)." });
      return;
    }

    setInfo(null);
    setStatus({ kind: "fetching" });
    try {
      const data = await fetchVideoInfo(value);
      setInfo(data);
      const usable = data.resolutions.filter((r) => !r.too_large);
      const preferred = usable.find((r) => r.height === 720) ?? usable.at(-1) ?? data.resolutions[0];
      setResolution(preferred?.height ?? null);
      setStatus({ kind: "idle" });
    } catch (err) {
      setStatus({ kind: "error", message: messageOf(err) });
    }
  }

  async function handleDownload() {
    if (!info || !resolution) return;
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const { filename, filesize } = await downloadVideo(
        info.url,
        resolution,
        (progress) => setStatus({ kind: "downloading", progress }),
        controller.signal,
      );
      const size = formatBytes(filesize);
      setStatus({
        kind: "success",
        message: `Your download has started: “${filename}”${size ? ` (${size})` : ""}. Check your browser’s downloads.`,
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        setStatus({ kind: "idle" });
      } else {
        setStatus({ kind: "error", message: messageOf(err) });
      }
    } finally {
      abortRef.current = null;
    }
  }

  const selected = info?.resolutions.find((r) => r.height === resolution);

  return (
    <div className="w-full space-y-6">
      <form onSubmit={handleFetch} className="space-y-3">
        <label htmlFor="url" className="sr-only">
          YouTube video URL
        </label>
        <div className="flex gap-2">
          <input
            id="url"
            type="url"
            inputMode="url"
            autoComplete="off"
            spellCheck={false}
            placeholder="https://www.youtube.com/watch?v=…"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={busy}
            className="min-w-0 flex-1 rounded-xl border border-zinc-300 bg-white px-4 py-3.5 text-base text-zinc-900 shadow-sm outline-none transition placeholder:text-zinc-400 focus:border-red-500 focus:ring-4 focus:ring-red-500/15 disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:placeholder:text-zinc-500"
          />
          <button
            type="button"
            onClick={handlePaste}
            disabled={busy}
            className="shrink-0 rounded-xl border border-zinc-300 bg-white px-4 text-sm font-medium text-zinc-700 shadow-sm transition hover:bg-zinc-50 disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800"
          >
            Paste
          </button>
        </div>
        <button
          type="submit"
          disabled={busy}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-zinc-900 px-4 py-3 text-sm font-semibold text-white transition hover:bg-zinc-700 disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          {status.kind === "fetching" && <Spinner />}
          {status.kind === "fetching" ? "Fetching video…" : "Fetch Video"}
        </button>
      </form>

      {info && (
        <section className="overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          {info.thumbnail && (
            <div className="relative aspect-video bg-zinc-100 dark:bg-zinc-800">
              {/* eslint-disable-next-line @next/next/no-img-element -- remote thumbnail, no optimisation needed */}
              <img src={info.thumbnail} alt="" className="h-full w-full object-cover" />
              {formatDuration(info.duration) && (
                <span className="absolute bottom-2 right-2 rounded-md bg-black/75 px-1.5 py-0.5 text-xs font-medium text-white">
                  {formatDuration(info.duration)}
                </span>
              )}
            </div>
          )}
          <div className="space-y-4 p-4 sm:p-5">
            <div>
              <h2 className="line-clamp-2 font-semibold leading-snug text-zinc-900 dark:text-zinc-100">{info.title}</h2>
              {info.uploader && <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">{info.uploader}</p>}
            </div>

            <div className="flex flex-col gap-2 sm:flex-row">
              <label htmlFor="resolution" className="sr-only">
                Resolution
              </label>
              <select
                id="resolution"
                value={resolution ?? ""}
                onChange={(e) => setResolution(Number(e.target.value))}
                disabled={busy}
                className="flex-1 rounded-xl border border-zinc-300 bg-white px-3 py-3 text-sm text-zinc-900 outline-none focus:border-red-500 focus:ring-4 focus:ring-red-500/15 disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100"
              >
                {info.resolutions.map((r) => (
                  <option key={r.height} value={r.height} disabled={r.too_large}>
                    {r.label}
                    {formatBytes(r.filesize) ? ` · ~${formatBytes(r.filesize)}` : ""}
                    {r.too_large ? ` (over ${info.max_filesize_label} limit)` : ""}
                  </option>
                ))}
              </select>
              {status.kind === "downloading" ? (
                <button
                  type="button"
                  onClick={() => abortRef.current?.abort()}
                  className="rounded-xl border border-zinc-300 px-5 py-3 text-sm font-semibold text-zinc-700 transition hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
                >
                  Cancel
                </button>
              ) : (
                <button
                  type="button"
                  onClick={handleDownload}
                  disabled={busy || !selected || selected.too_large}
                  className="rounded-xl bg-red-600 px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-red-500 disabled:opacity-60"
                >
                  Download Video
                </button>
              )}
            </div>
          </div>
        </section>
      )}

      <StatusMessage status={status} />
    </div>
  );
}

function StatusMessage({ status }: { status: Status }) {
  if (status.kind === "error") {
    return (
      <p role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-300">
        {status.message}
      </p>
    );
  }
  if (status.kind === "success") {
    return (
      <p role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-300">
        {status.message}
      </p>
    );
  }
  if (status.kind !== "downloading") return null;

  const { progress } = status;
  const percent =
    progress.phase === "downloading" && progress.total
      ? Math.min(100, (progress.downloaded / progress.total) * 100)
      : null;
  const label =
    progress.phase === "queued"
      ? "Starting…"
      : progress.phase === "merging"
        ? "Merging video and audio… almost done."
        : `Preparing on the server… ${formatBytes(progress.downloaded) ?? "0 KB"}${progress.total ? ` of ${formatBytes(progress.total)}` : ""}`;

  return (
    <div role="status" className="space-y-2">
      <div className="flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-400">
        <Spinner />
        <span>{label}</span>
        {percent !== null && <span className="ml-auto tabular-nums">{Math.floor(percent)}%</span>}
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
        {percent !== null ? (
          <div className="h-full rounded-full bg-red-600 transition-[width]" style={{ width: `${percent}%` }} />
        ) : (
          <div className="h-full w-1/3 animate-[indeterminate_1.2s_ease-in-out_infinite] rounded-full bg-red-600" />
        )}
      </div>
    </div>
  );
}
