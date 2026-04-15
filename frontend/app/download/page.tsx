import { redirect } from "next/navigation";

import DownloadClient from "./DownloadClient";

type ExtractResult = {
  title: string;
  thumbnail?: string | null;
  video_url?: string;
  stream_url?: string;
};

type StoredData = ExtractResult & {
  source_url?: string;
};

function getApiBaseUrl() {
  const raw =
    process.env.NEXT_PUBLIC_API_URL ||
    process.env.API_URL ||
    "https://pinterest-downloader-production-5d58.up.railway.app/";
  return raw.trim().replace(/\/+$/, "");
}

async function fetchExtracted(url: string): Promise<{
  data: StoredData | null;
  loadError: string | null;
}> {
  const apiBaseUrl = getApiBaseUrl();
  if (!apiBaseUrl) {
    return { data: null, loadError: "Missing NEXT_PUBLIC_API_URL." };
  }

  const res = await fetch(`${apiBaseUrl}/extract`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
    cache: "no-store",
  });

  const contentType = res.headers.get("content-type") || "";
  const isJson = contentType.toLowerCase().includes("application/json");
  const rawBody = await res.text();
  const payload = isJson ? (JSON.parse(rawBody) as unknown) : rawBody;

  if (res.ok) {
    if (
      typeof payload !== "object" ||
      payload === null ||
      !("title" in payload) ||
      typeof (payload as { title: unknown }).title !== "string"
    ) {
      return { data: null, loadError: "Unexpected response from the server." };
    }
    return { data: { ...(payload as ExtractResult), source_url: url }, loadError: null };
  }

  if (typeof payload === "object" && payload !== null) {
    const streamUrl = (payload as { stream_url?: unknown }).stream_url;
    const title = (payload as { title?: unknown }).title;
    if (typeof streamUrl === "string" && streamUrl.trim()) {
      const extracted = {
        title: typeof title === "string" && title.trim() ? title : "Pinterest Video",
        thumbnail:
          typeof (payload as { thumbnail?: unknown }).thumbnail === "string"
            ? ((payload as { thumbnail?: unknown }).thumbnail as string)
            : null,
        stream_url: streamUrl,
      } satisfies ExtractResult;
      return { data: { ...extracted, source_url: url }, loadError: null };
    }

    const maybeMessage = (payload as { message?: unknown }).message;
    if (typeof maybeMessage === "string" && maybeMessage.trim()) {
      return { data: null, loadError: maybeMessage };
    }
  }

  return { data: null, loadError: "Request failed. Please try a different Pinterest link." };
}

export default async function DownloadPage({
  searchParams,
}: {
  searchParams: Record<string, string | string[] | undefined>;
}) {
  const raw = searchParams.url;
  const url = (Array.isArray(raw) ? raw[0] : raw || "").trim();
  if (!url) redirect("/");

  const { data, loadError } = await fetchExtracted(url);
  return <DownloadClient data={data} loadError={loadError} />;
}
