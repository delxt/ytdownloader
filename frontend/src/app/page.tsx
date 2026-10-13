import Downloader from "@/components/Downloader";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col justify-center px-4 py-12 sm:py-20">
      <header className="mb-8 text-center">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-red-600 text-white shadow-sm">
          <svg viewBox="0 0 24 24" fill="currentColor" className="h-6 w-6" aria-hidden>
            <path d="M12 3a1 1 0 0 1 1 1v9.59l3.3-3.3a1 1 0 1 1 1.4 1.42l-5 5a1 1 0 0 1-1.4 0l-5-5a1 1 0 1 1 1.4-1.42l3.3 3.3V4a1 1 0 0 1 1-1ZM5 19a1 1 0 1 0 0 2h14a1 1 0 1 0 0-2H5Z" />
          </svg>
        </div>
        <h1 className="text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50">Tube Downloader</h1>
        <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">
          Paste a YouTube link, pick a resolution, and download in up to 1080p.
        </p>
      </header>

      <Downloader />

      <footer className="mt-10 text-center text-xs leading-relaxed text-zinc-400 dark:text-zinc-500">
        Only download videos you own or have permission to download. Respect YouTube&apos;s Terms of Service and
        copyright law.
      </footer>
    </main>
  );
}
