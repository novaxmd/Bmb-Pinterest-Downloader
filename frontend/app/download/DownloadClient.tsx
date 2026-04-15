"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

type ExtractResult = {
  title: string;
  thumbnail?: string | null;
  video_url?: string;
  stream_url?: string;
};

type StoredData = ExtractResult & {
  source_url?: string;
};

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "https://pinterest-downloader-production-5d58.up.railway.app/")
  .trim()
  .replace(/\/+$/, "");

function apiUrl(path: string) {
  if (!API_BASE) return path;
  return `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
}

function proxiedUrl(url: string) {
  return apiUrl(`/proxy?url=${encodeURIComponent(url)}`);
}

export default function DownloadClient({
  data,
  loadError,
}: {
  data: StoredData | null;
  loadError: string | null;
}) {
  const router = useRouter();
  const [copied, setCopied] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState<string | null>(null);

  const canRender = useMemo(() => Boolean(data && data.title), [data]);

  async function copyText(text: string, label: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(label);
      window.setTimeout(() => setCopied(null), 1500);
    } catch {
      setCopied("Copy failed");
      window.setTimeout(() => setCopied(null), 1500);
    }
  }

  function downloadAnother() {
    router.push("/");
  }

  async function handleDownload(e?: React.MouseEvent<HTMLButtonElement>) {
    e?.preventDefault();
    const sourceUrl = (data?.source_url || "").trim();
    if (!sourceUrl) {
      setCopied("Missing source URL");
      window.setTimeout(() => setCopied(null), 1500);
      return;
    }
    if (loading) return;

    setLoading(true);
    setLoadingMessage("Processing...");

    const timeoutId = window.setTimeout(() => {
      setLoadingMessage("Preparing your video...");
    }, 2000);

    try {
      const res = await fetch(apiUrl("/download"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: sourceUrl }),
      });

      const contentType = res.headers.get("content-type") || "";
      if (contentType.toLowerCase().includes("video")) {
        const blob = await res.blob();
        const downloadUrl = window.URL.createObjectURL(blob);

        const safeTitle = (data?.title || "video").replace(/[^A-Za-z0-9._ -]+/g, "").trim() || "video";
        const a = document.createElement("a");
        a.href = downloadUrl;
        a.download = `${safeTitle.slice(0, 80)}.mp4`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(downloadUrl);
        setCopied("Download started");
        window.setTimeout(() => setCopied(null), 1500);
        return;
      }

      const json = (await res.json()) as unknown;
      const videoUrl = (json as { video_url?: unknown }).video_url;
      if (typeof videoUrl === "string" && videoUrl.trim()) {
        window.open(videoUrl, "_blank", "noopener,noreferrer");
        return;
      }

      const msg = (json as { message?: unknown }).message;
      setCopied(typeof msg === "string" && msg.trim() ? msg : "Download failed");
      window.setTimeout(() => setCopied(null), 1500);
    } catch {
      setCopied("Download failed");
      window.setTimeout(() => setCopied(null), 1500);
    } finally {
      window.clearTimeout(timeoutId);
      setLoading(false);
      setLoadingMessage(null);
    }
  }

  return (
    <div className="min-h-screen bg-zinc-50 font-sans text-zinc-950">
      <header className="sticky top-0 z-20 border-b border-zinc-200 bg-white/90 backdrop-blur">
        <nav className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4 sm:px-6">
          <Link href="/" className="text-base font-semibold tracking-tight text-zinc-950">
            Pinterest Downloader
          </Link>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={downloadAnother}
              className="inline-flex h-10 items-center justify-center rounded-2xl bg-[#E60023] px-4 text-sm font-semibold text-white transition-colors hover:bg-[#c7001f]"
            >
              Download Another
            </button>
          </div>
        </nav>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-10 sm:px-6 sm:py-14">
        <section className="mb-8">
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
            Your download is ready
          </h1>
          <p className="mt-2 text-zinc-600">
            Choose the best option below. If MP4 isn’t available, use HLS tools.
          </p>
        </section>

        {copied ? (
          <div className="mb-5 rounded-2xl border border-zinc-200 bg-white px-4 py-3 text-sm text-zinc-700">
            {copied}
          </div>
        ) : null}

        {loadError ? (
          <section className="rounded-3xl border border-red-200 bg-red-50 p-6 text-red-900 shadow-sm">
            <h2 className="text-base font-semibold">Couldn’t fetch this link</h2>
            <p className="mt-2 text-sm leading-relaxed">{loadError}</p>
            <div className="mt-5">
              <button
                type="button"
                onClick={downloadAnother}
                className="inline-flex h-11 items-center justify-center rounded-2xl bg-[#E60023] px-5 font-semibold text-white transition-colors hover:bg-[#c7001f]"
              >
                Try another link
              </button>
            </div>
          </section>
        ) : canRender && data ? (
          <section className="grid gap-8 lg:grid-cols-2">
            <div className="rounded-3xl border border-zinc-200 bg-white p-5 shadow-sm sm:p-7">
              {data.thumbnail ? (
                <img
                  src={proxiedUrl(data.thumbnail)}
                  alt={data.title}
                  className="aspect-[4/3] w-full rounded-2xl border border-zinc-200 object-cover"
                />
              ) : (
                <div className="aspect-[4/3] w-full rounded-2xl border border-zinc-200 bg-zinc-100" />
              )}
            </div>

            <div className="rounded-3xl border border-zinc-200 bg-white p-5 shadow-sm sm:p-7">
              <h2 className="text-xl font-semibold leading-snug sm:text-2xl">
                {data.title}
              </h2>

              <div className="mt-6 grid gap-3 sm:grid-cols-2">
                <button
                  type="button"
                  onClick={handleDownload}
                  disabled={loading}
                  className="inline-flex h-12 items-center justify-center rounded-2xl bg-zinc-950 px-5 font-semibold text-white transition-colors hover:bg-zinc-900 disabled:cursor-not-allowed disabled:opacity-60 sm:col-span-2"
                >
                  {loading ? loadingMessage || "Processing..." : "Download Video"}
                </button>
                {data.video_url ? (
                  <>
                    <a
                      href={data.video_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex h-12 items-center justify-center rounded-2xl bg-[#E60023] px-5 font-semibold text-white transition-colors hover:bg-[#c7001f]"
                    >
                      HD Download
                    </a>
                    <a
                      href={data.video_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex h-12 items-center justify-center rounded-2xl border border-zinc-200 bg-white px-5 font-semibold text-zinc-900 transition-colors hover:bg-zinc-50"
                    >
                      Fast Download
                    </a>
                  </>
                ) : data.stream_url ? (
                  <>
                    <a
                      href={apiUrl(
                        `/hls?url=${encodeURIComponent(data.stream_url)}&title=${encodeURIComponent(data.title)}&format=mp4`
                      )}
                      className="inline-flex h-12 items-center justify-center rounded-2xl bg-[#E60023] px-5 font-semibold text-white transition-colors hover:bg-[#c7001f]"
                    >
                      Convert to MP4
                    </a>
                    <a
                      href={apiUrl(
                        `/hls?url=${encodeURIComponent(data.stream_url)}&title=${encodeURIComponent(data.title)}`
                      )}
                      className="inline-flex h-12 items-center justify-center rounded-2xl border border-zinc-200 bg-white px-5 font-semibold text-zinc-900 transition-colors hover:bg-zinc-50"
                    >
                      Fast Download
                    </a>
                  </>
                ) : null}

                {data.stream_url ? (
                  <a
                    href={data.stream_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex h-12 items-center justify-center rounded-2xl border border-zinc-200 bg-white px-5 font-semibold text-zinc-900 transition-colors hover:bg-zinc-50"
                  >
                    HD Download
                  </a>
                ) : null}

                {data.source_url ? (
                  <a
                    href={data.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex h-12 items-center justify-center rounded-2xl border border-zinc-200 bg-white px-5 font-semibold text-zinc-900 transition-colors hover:bg-zinc-50"
                  >
                    Open Pinterest
                  </a>
                ) : null}

                {data.stream_url ? (
                  <>
                    <div className="rounded-2xl border border-zinc-200 bg-zinc-50 px-4 py-3 text-sm text-zinc-700 sm:col-span-2">
                      Direct MP4 available नाही. Server conversion fail झालं तर HLS (.ts) download करून ffmpeg/yt-dlp ने MP4 मध्ये convert करा.
                    </div>

                    <button
                      type="button"
                      onClick={() =>
                        copyText(
                          `ffmpeg -i "${data.stream_url}" -c copy "${data.title}.mp4"`,
                          "FFmpeg command copied"
                        )
                      }
                      className="inline-flex h-12 items-center justify-center rounded-2xl border border-zinc-200 bg-white px-5 font-semibold text-zinc-900 transition-colors hover:bg-zinc-50"
                    >
                      Copy FFmpeg
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        copyText(
                          `yt-dlp -o "%(title)s.%(ext)s" "${data.stream_url}"`,
                          "yt-dlp command copied"
                        )
                      }
                      className="inline-flex h-12 items-center justify-center rounded-2xl border border-zinc-200 bg-white px-5 font-semibold text-zinc-900 transition-colors hover:bg-zinc-50"
                    >
                      Copy yt-dlp
                    </button>
                  </>
                ) : null}

                <button
                  type="button"
                  onClick={downloadAnother}
                  className="inline-flex h-12 items-center justify-center rounded-2xl border border-zinc-200 bg-white px-5 font-semibold text-zinc-900 transition-colors hover:bg-zinc-50 sm:col-span-2"
                >
                  Download Another Video
                </button>
              </div>

              <p className="mt-5 text-sm text-zinc-500">
                {data.video_url
                  ? "If the download doesn’t start automatically, open the direct link and save the video from your browser."
                  : data.stream_url
                    ? "Direct MP4 उपलब्ध नाही. Server MP4 download try करा; नाही झालं तर HLS (.ts) download करून ffmpeg/yt-dlp वापरा."
                    : ""}
              </p>
            </div>
          </section>
        ) : (
          <section className="rounded-3xl border border-zinc-200 bg-white p-6 shadow-sm">
            <div className="flex items-center gap-3">
              <span className="h-5 w-5 animate-spin rounded-full border-2 border-zinc-600 border-t-transparent" />
              <p className="text-sm text-zinc-700">Loading your result...</p>
            </div>
          </section>
        )}
      </main>

      <footer className="border-t border-zinc-800 bg-zinc-950 text-zinc-200">
        <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
          <div className="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex flex-col gap-2">
              <div className="text-base font-semibold">Pinterest Downloader</div>
              <div className="text-sm text-zinc-400">© 2026. All rights reserved.</div>
            </div>
            <div className="flex flex-wrap gap-4 text-sm text-zinc-300">
              <Link href="/privacy-policy" className="hover:text-white">
                Privacy Policy
              </Link>
              <Link href="/terms-of-service" className="hover:text-white">
                Terms of Service
              </Link>
              <Link href="/" className="hover:text-white">
                Home
              </Link>
            </div>
          </div>
          <p className="mt-6 text-sm leading-relaxed text-zinc-400">
            This site is not affiliated with Pinterest. Use it only to download content you
            have rights to use.
          </p>
        </div>
      </footer>
    </div>
  );
}
