# Tube Downloader

A small web app for downloading YouTube videos in 360p, 480p, 720p HD or 1080p Full HD. You paste a link, fetch the video info, pick a resolution and download the file.

> **Use responsibly.** Only download videos that you own or have permission to download, and follow YouTube's Terms of Service and copyright law. The app does not circumvent DRM or bypass access controls: private, members-only, age-restricted and DRM-protected videos are rejected.

```
ytdownloader/
├── backend/    Python FastAPI + yt-dlp + FFmpeg
│   ├── app/
│   │   ├── main.py        API routes, CORS, error handling
│   │   ├── video.py       URL validation, yt-dlp info/download, format selection
│   │   ├── ratelimit.py   per-IP rate limiting
│   │   └── config.py      settings from environment variables
│   ├── requirements.txt
│   └── .env.example
└── frontend/   Next.js (App Router) + TypeScript + Tailwind CSS
    ├── src/app/                   page and layout
    ├── src/components/Downloader.tsx
    ├── src/lib/api.ts             API client
    └── .env.example
```

## How it works

| Endpoint | Body | Result |
|---|---|---|
| `POST /api/video/info` | `{ "url": "..." }` | Title, thumbnail, duration, uploader and the available resolutions with estimated sizes |
| `POST /api/video/download` | `{ "url": "...", "resolution": 720 }` | Starts a download job and returns `{ id, status, ... }` (202) |
| `GET /api/video/download/{id}` | – | Job status: `queued`, `downloading` or `merging` (with `downloaded`/`total` bytes), then `ready`, `error` or `cancelled` |
| `GET /api/video/download/{id}/file` | – | The finished MP4 as an attachment. The file is deleted from the server once it has been sent |
| `DELETE /api/video/download/{id}` | – | Cancels the job and deletes its files |
| `GET /api/health` | – | `{ "status": "ok" }` |

- **URL validation:** only `youtube.com`, `www.youtube.com`, `m.youtube.com` and `youtu.be` are accepted. Watch, `youtu.be`, Shorts, embed and live URL forms all work. The video ID is extracted and the request goes to a rebuilt canonical URL, so playlist parameters and other hosts never reach yt-dlp.
- **Formats:** the backend picks the best video stream at the chosen resolution, preferring H.264, and the best audio stream, preferring AAC. FFmpeg merges them into an MP4 that plays on any device.
- **Large files (up to 10 GB by default):** the server prepares the file in a background job while the page polls its progress. When the file is ready, the browser downloads it with its own download manager, so the video never has to fit in page memory.
- **Temporary storage:** each job gets its own temp directory. The directory is deleted after the file is sent, when the job fails or is cancelled, and after `JOB_TTL_SECONDS` if the file is never collected. Leftover folders from a crashed run are removed when the server starts. Before a job starts, the server checks that the disk has about 2.2× the file size free, because the separate streams and the merged file exist at the same time for a moment.
- **Limits:**
  - File size: checked before the download starts, during it and after merging.
  - Download time.
  - Info request timeout.
  - Per-IP rate limits.
  - Maximum number of concurrent downloads.
  - All of these are configurable.
- **Errors:** clients get friendly messages only, such as "This video is private." Internal errors and file paths are only logged on the server.

## Requirements

- **Python** 3.10+ (tested with 3.14)
- **Node.js** 20+ (tested with 25). yt-dlp also uses Node as its JavaScript runtime for YouTube.
- **FFmpeg** (see below)

### FFmpeg setup

To merge HD video and audio, the backend looks for FFmpeg in this order:

1. `FFMPEG_LOCATION` in `backend/.env`. This can be the path to `ffmpeg` or to its folder.
2. `ffmpeg` on the system `PATH`.
3. The static binary that ships with the `imageio-ffmpeg` pip package. It is installed with `requirements.txt`, so local development works without any extra setup.

On a server, installing the system package is recommended:

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install -y ffmpeg
# Fedora / RHEL
sudo dnf install -y ffmpeg
# macOS
brew install ffmpeg
# Windows (any one of these)
winget install Gyan.FFmpeg
choco install ffmpeg
```

Check that it is installed with `ffmpeg -version`.

### JavaScript runtime for yt-dlp

YouTube extraction in yt-dlp needs a JavaScript runtime. By default (`JS_RUNTIMES=deno,node`), the backend uses [Deno](https://deno.com) if it is installed and falls back to Node.js otherwise. Because Node is already required for the frontend, no extra install is needed.

## Local development

### Quick start (from the project root)

```bash
npm run setup   # one time: creates backend/.venv, installs Python + npm deps, copies .env files
npm run dev     # starts the API on :8000 and the web app on :3000 together (Ctrl+C stops both)
```

To run the two apps separately instead, follow these steps.

**1. Backend** (http://localhost:8000)

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Linux/macOS:  source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # Windows: copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

**2. Frontend** (http://localhost:3000)

```bash
cd frontend
npm install
cp .env.example .env.local      # Windows: copy .env.example .env.local
npm run dev
```

Open http://localhost:3000, paste a link and click **Fetch Video**. Then pick a resolution and click **Download Video**.

## Configuration

### `backend/.env`

| Variable | Default | Description |
|---|---|---|
| `ALLOWED_ORIGINS` | `http://localhost:3000` | Comma-separated origins allowed by CORS (your frontend URL) |
| `MAX_FILESIZE_MB` | `10240` | Largest file that will be produced (10 GB) |
| `INFO_TIMEOUT_SECONDS` | `30` | Timeout for fetching video info |
| `DOWNLOAD_TIMEOUT_SECONDS` | `3600` | A job is stopped if downloading takes longer than this |
| `RATE_LIMIT_INFO_PER_MINUTE` | `20` | Info requests per IP per minute |
| `RATE_LIMIT_DOWNLOAD_PER_MINUTE` | `5` | Download requests per IP per minute |
| `MAX_CONCURRENT_DOWNLOADS` | `3` | Jobs that may run at the same time. Further requests get "server busy" (503) |
| `JOB_TTL_SECONDS` | `1800` | How long a finished file waits to be downloaded before it is deleted |
| `TRUST_PROXY` | `false` | Set `true` behind nginx so the client IP is read from `X-Forwarded-For` |
| `JS_RUNTIMES` | `deno,node` | JavaScript runtimes yt-dlp may use |
| `FFMPEG_LOCATION` | *(empty)* | Explicit FFmpeg path |
| `TEMP_DIR` | system temp | Where temporary downloads are written |

### `frontend/.env.local`

| Variable | Description |
|---|---|
| `NEXT_PUBLIC_API_URL` | Backend URL as seen from the browser, for example `http://localhost:8000`. Leave it **empty** when nginx serves `/api` on the same domain as the frontend. This value is baked in at build time, so rebuild after changing it. |

## Production (VPS)

These steps assume Ubuntu, a domain such as `tube.example.com` pointing at the server, and the project in `/opt/ytdownloader`. Both apps listen only on localhost, and nginx serves everything on a single domain:

```
browser ──► nginx :443 ──► /api/*  → FastAPI  127.0.0.1:8000
                       └─► /*      → Next.js  127.0.0.1:3000
```

### 1. Install system packages

```bash
sudo apt update && sudo apt install -y python3-venv ffmpeg nginx
# Node.js 20+ (e.g. via NodeSource or nvm)
```

### 2. Backend

```bash
cd /opt/ytdownloader/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# edit .env:
#   ALLOWED_ORIGINS=https://tube.example.com
#   TRUST_PROXY=true
```

Run the backend with a **single worker**. Download jobs, the rate limiter and the concurrent-download limit are kept in memory per process. Make sure the temp disk (or `TEMP_DIR`) has enough free space: up to about 22 GB per running 10 GB job. Save the following as `/etc/systemd/system/tube-backend.service`:

```ini
[Unit]
Description=Tube Downloader API
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/ytdownloader/backend
ExecStart=/opt/ytdownloader/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers
Restart=always

[Install]
WantedBy=multi-user.target
```

### 3. Frontend

```bash
cd /opt/ytdownloader/frontend
npm ci
echo "NEXT_PUBLIC_API_URL=" > .env.production.local   # same-origin /api via nginx
npm run build
```

Save the following as `/etc/systemd/system/tube-frontend.service`:

```ini
[Unit]
Description=Tube Downloader frontend
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/ytdownloader/frontend
ExecStart=/usr/bin/npm run start -- -p 3000 -H 127.0.0.1
Environment=NODE_ENV=production
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start both services:

```bash
sudo chown -R www-data:www-data /opt/ytdownloader
sudo systemctl daemon-reload
sudo systemctl enable --now tube-backend tube-frontend
```

### 4. nginx

Save the following as `/etc/nginx/sites-available/tube`, then link it into `sites-enabled`:

```nginx
server {
    server_name tube.example.com;

    client_max_body_size 1m;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;     # multi-GB files can take a while to send to slow clients
        proxy_send_timeout 3600s;
        proxy_buffering off;          # stream large files straight to the client
    }

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Test the config, reload nginx and add HTTPS. The browser **Paste** button only works over HTTPS or on localhost.

```bash
sudo ln -s /etc/nginx/sites-available/tube /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo apt install -y certbot python3-certbot-nginx && sudo certbot --nginx -d tube.example.com
```

### Keeping yt-dlp current

YouTube changes often, so keep yt-dlp up to date:

```bash
cd /opt/ytdownloader/backend && .venv/bin/pip install -U "yt-dlp[default]" && sudo systemctl restart tube-backend
```

## Troubleshooting

- **"YouTube is temporarily limiting requests from this server":** YouTube has rate-limited or bot-checked the server's IP. Wait a while, or lower the rate limits.
- **"The selected format isn't available":** update yt-dlp (see above).
- **Merging fails:** check that FFmpeg is installed (`ffmpeg -version`) or set `FFMPEG_LOCATION`.
- **CORS errors in the browser:** `ALLOWED_ORIGINS` must exactly match the frontend origin, including the scheme and the port.
