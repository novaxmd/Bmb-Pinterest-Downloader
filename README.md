# Pinterest Video Downloader (Next.js + Vercel Python Function)

Frontend is built with Next.js App Router. The backend extractor is a raw Vercel Python Function powered by `yt-dlp`.

## API

- Endpoint: `POST /api/download`
- Body: `{ "url": "https://www.pinterest.com/pin/..." }`
- Response: `{ "title": "...", "thumbnail": "...", "video_url": "https://..." }`

The Python function lives at `api/download.py` and returns clean JSON errors for invalid inputs and extraction failures.

## Local Development

Run the Next.js frontend:

```bash
npm run dev
```

Note: `npm run dev` will not run `api/download.py` (Python) locally, so `/api/download` will 404.

To test the full stack locally (Next.js + Python Function), use Vercel CLI:

```bash
npx vercel dev
```

The production deployment on Vercel will automatically serve `api/download.py` at `/api/download`.

## Deploy to Vercel

- Push this repo to GitHub (or import directly).
- Create a new Vercel project and deploy.

Python dependencies are declared in `requirements.txt`. Vercel routing configuration is in `vercel.json`.
