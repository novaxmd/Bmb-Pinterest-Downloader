import json
import os
import re
import hashlib
import time
import shutil
import subprocess
import tempfile
import uuid
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

import hls as hls_mod


_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

_UPSTASH_REDIS_REST_URL = (os.environ.get("UPSTASH_REDIS_REST_URL") or "").strip()
_UPSTASH_REDIS_REST_TOKEN = (os.environ.get("UPSTASH_REDIS_REST_TOKEN") or "").strip()
_CACHE_TTL_SECONDS = 60 * 30


def _normalize_url(raw_url: str) -> str:
    raw_url = (raw_url or "").strip()
    if not raw_url:
        return ""
    parsed = urlparse(raw_url)
    if parsed.scheme:
        return raw_url
    return f"https://{raw_url}"


def _is_pinterest_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    return host == "pin.it" or host.endswith(".pin.it") or host == "pinterest.com" or host.endswith(".pinterest.com")


def _looks_like_direct_mp4(u: str) -> bool:
    if not isinstance(u, str) or not u:
        return False
    ul = u.lower()
    if ".m3u8" in ul:
        return False
    return bool(re.search(r"\.mp4(\?|$)", ul))


def _pick_best_mp4_url(info: dict) -> str:
    formats = info.get("formats") or []
    candidates = []
    for f in formats:
        if not isinstance(f, dict):
            continue
        url = f.get("url")
        if not url:
            continue
        ext = (f.get("ext") or "").lower()
        mime_type = (f.get("mime_type") or "").lower()
        if ext != "mp4" and "video/mp4" not in mime_type and not _looks_like_direct_mp4(url):
            continue
        if ".m3u8" in str(url).lower():
            continue
        height = f.get("height") or 0
        tbr = f.get("tbr") or 0
        filesize = f.get("filesize") or f.get("filesize_approx") or 0
        has_audio = 1 if (f.get("acodec") and f.get("acodec") != "none") else 0
        has_video = 1 if (f.get("vcodec") and f.get("vcodec") != "none") else 0
        score = (has_video, has_audio, height, tbr, filesize)
        candidates.append((score, url))
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    direct_url = info.get("url")
    if isinstance(direct_url, str) and direct_url:
        ext = info.get("ext")
        if ext == "mp4" or _looks_like_direct_mp4(direct_url):
            return direct_url
    return ""


def _pick_best_hls_url(info: dict) -> str:
    formats = info.get("formats") or []
    candidates = []
    for f in formats:
        if not isinstance(f, dict):
            continue
        url = f.get("url")
        if not isinstance(url, str) or not url:
            continue
        if ".m3u8" not in url.lower():
            continue
        height = f.get("height") or 0
        tbr = f.get("tbr") or 0
        has_audio = 1 if (f.get("acodec") and f.get("acodec") != "none") else 0
        has_video = 1 if (f.get("vcodec") and f.get("vcodec") != "none") else 0
        candidates.append(((has_video, has_audio, height, tbr, len(url)), url))
    if not candidates:
        return ""
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _fetch_html(url: str) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        method="GET",
    )
    with urlopen(req, timeout=20) as resp:
        raw = resp.read()
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="ignore")


def _extract_meta(html: str, key: str) -> str:
    patterns = [
        rf'<meta[^>]+property=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{re.escape(key)}["\']',
        rf'<meta[^>]+name=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']{re.escape(key)}["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, flags=re.IGNORECASE)
        if m:
            return unescape(m.group(1)).strip()
    return ""


def _score_mp4_url(u: str) -> tuple:
    m = re.search(r"(\d{3,4})p", u)
    p = int(m.group(1)) if m else 0
    return (p, len(u))


def _extract_from_html(url: str) -> dict:
    html = _fetch_html(url)

    title = _extract_meta(html, "og:title") or _extract_meta(html, "twitter:title")
    thumbnail = _extract_meta(html, "og:image") or _extract_meta(html, "twitter:image")
    og_video = _extract_meta(html, "og:video") or _extract_meta(html, "og:video:secure_url")

    candidates = []
    if og_video and ".mp4" in og_video:
        candidates.append(og_video)

    for m in re.finditer(r"https:\\/\\/[^\"'\\s<>]+?\\.mp4[^\"'\\s<>]*", html, flags=re.IGNORECASE):
        candidates.append(m.group(0))
    for m in re.finditer(r"https://[^\"'\\s<>]+?\\.mp4[^\"'\\s<>]*", html, flags=re.IGNORECASE):
        candidates.append(m.group(0))

    normalized = []
    for u in candidates:
        u = unescape(u)
        u = u.replace("\\/", "/")
        u = u.strip()
        if u.startswith("https://"):
            normalized.append(u)

    normalized = list(dict.fromkeys(normalized))
    normalized.sort(key=_score_mp4_url, reverse=True)

    video_url = normalized[0] if normalized else ""
    if not video_url:
        return {}

    return {
        "title": title or "Pinterest Video",
        "thumbnail": thumbnail or None,
        "video_url": video_url,
    }

def _now_ms() -> int:
    return int(time.time() * 1000)


def _log_event(event: dict):
    try:
        event.setdefault("ts_ms", _now_ms())
        print(json.dumps(event, ensure_ascii=False))
    except Exception:
        return


def _kv_enabled() -> bool:
    return bool(_UPSTASH_REDIS_REST_URL and _UPSTASH_REDIS_REST_TOKEN)


def _kv_command(command: list):
    if not _kv_enabled():
        return None
    body = json.dumps({"command": command}).encode("utf-8")
    req = Request(
        _UPSTASH_REDIS_REST_URL,
        headers={
            "Authorization": f"Bearer {_UPSTASH_REDIS_REST_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        data=body,
        method="POST",
    )
    with urlopen(req, timeout=10) as resp:
        raw = resp.read()
        return json.loads(raw.decode("utf-8"))


def _cache_key(url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return f"cache:download:{digest}"


def _cache_get(url: str):
    if not _kv_enabled():
        return None
    try:
        res = _kv_command(["GET", _cache_key(url)])
        if not isinstance(res, dict):
            return None
        raw = res.get("result")
        if not isinstance(raw, str) or not raw:
            return None
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return None
        status = parsed.get("status")
        payload = parsed.get("payload")
        if not isinstance(status, int) or not isinstance(payload, dict):
            return None
        return (status, payload)
    except Exception:
        return None


def _cache_set(url: str, status: int, payload: dict):
    if not _kv_enabled():
        return
    try:
        value = json.dumps({"status": status, "payload": payload}, ensure_ascii=False)
        _kv_command(["SETEX", _cache_key(url), int(_CACHE_TTL_SECONDS), value])
    except Exception:
        return


def convert_hls_to_mp4(stream_url: str) -> str | None:
    stream_url = (stream_url or "").strip()
    if not stream_url:
        return None
    if not shutil.which("ffmpeg"):
        return None

    temp_dir = os.environ.get("TEMP_DIR") or tempfile.gettempdir()
    filename = f"{uuid.uuid4()}.mp4"
    output_path = os.path.join(temp_dir, filename)

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        stream_url,
        "-c",
        "copy",
        "-bsf:a",
        "aac_adtstoasc",
        output_path,
    ]

    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, check=False)
    except Exception:
        return None

    try:
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path
    except Exception:
        return None
    return None


def handle_extract(body: dict) -> tuple[int, dict]:
    started = time.perf_counter()

    url = _normalize_url(body.get("url") if isinstance(body, dict) else "")
    if not url:
        payload = {"error": "MISSING_URL", "message": "Provide a Pinterest URL in the 'url' field."}
        _log_event({"route": "extract", "method": "POST", "status": 400, "ms": int((time.perf_counter() - started) * 1000), "error": payload.get("error")})
        return 400, payload

    if not _is_pinterest_url(url):
        payload = {"error": "INVALID_DOMAIN", "message": "Only Pinterest URLs are supported."}
        _log_event({"route": "extract", "method": "POST", "status": 400, "ms": int((time.perf_counter() - started) * 1000), "error": payload.get("error"), "host": (urlparse(url).hostname or "").lower()})
        return 400, payload

    cached = _cache_get(url)
    if cached:
        status, payload = cached
        _log_event({"route": "extract", "method": "POST", "status": status, "ms": int((time.perf_counter() - started) * 1000), "cache": "hit"})
        return status, payload

    try:
        fast = _extract_from_html(url)
        if fast.get("video_url"):
            _cache_set(url, 200, fast)
            _log_event({"route": "extract", "method": "POST", "status": 200, "ms": int((time.perf_counter() - started) * 1000), "cache": "miss", "path": "fast_html"})
            return 200, fast
    except (HTTPError, URLError):
        pass
    except Exception:
        pass

    ydl_opts_primary = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "format": "best[ext=mp4]/best",
    }
    ydl_opts_secondary = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }

    try:
        with YoutubeDL(ydl_opts_primary) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as e:
        try:
            with YoutubeDL(ydl_opts_secondary) as ydl:
                info = ydl.extract_info(url, download=False)
        except DownloadError:
            message = str(e) or "Failed to extract a video from that Pinterest URL."
            if "Requested format is not available" in message:
                message = (
                    "This Pinterest link didn't expose a direct MP4 format. "
                    "Try a different pin or use a share link from the Pinterest app."
                )
            payload = {"error": "EXTRACTION_FAILED", "message": message}
            _cache_set(url, 422, payload)
            _log_event({"route": "extract", "method": "POST", "status": 422, "ms": int((time.perf_counter() - started) * 1000), "error": payload.get("error")})
            return 422, payload
        except Exception:
            payload = {"error": "INTERNAL_ERROR", "message": "Unexpected server error while extracting the video."}
            _cache_set(url, 500, payload)
            _log_event({"route": "extract", "method": "POST", "status": 500, "ms": int((time.perf_counter() - started) * 1000), "error": payload.get("error")})
            return 500, payload
    except Exception:
        payload = {"error": "INTERNAL_ERROR", "message": "Unexpected server error while extracting the video."}
        _cache_set(url, 500, payload)
        _log_event({"route": "extract", "method": "POST", "status": 500, "ms": int((time.perf_counter() - started) * 1000), "error": payload.get("error")})
        return 500, payload

    if isinstance(info, dict) and info.get("_type") == "playlist" and info.get("entries"):
        entries = [e for e in info.get("entries") if isinstance(e, dict)]
        if entries:
            info = entries[0]

    if not isinstance(info, dict):
        payload = {"error": "EXTRACTION_FAILED", "message": "No usable video metadata was returned by the extractor."}
        _cache_set(url, 422, payload)
        _log_event({"route": "extract", "method": "POST", "status": 422, "ms": int((time.perf_counter() - started) * 1000), "error": payload.get("error")})
        return 422, payload

    video_url = _pick_best_mp4_url(info)
    if not video_url:
        hls_url = _pick_best_hls_url(info)
        if hls_url:
            title = info.get("title") or "Pinterest Video"
            thumbnail = info.get("thumbnail")
            payload = {
                "error": "NO_DIRECT_MP4",
                "message": "This Pinterest video appears to be streaming-only (HLS) and does not provide a direct MP4 download link.",
                "title": title,
                "thumbnail": thumbnail,
                "stream_url": hls_url,
            }
            _cache_set(url, 422, payload)
            _log_event({"route": "extract", "method": "POST", "status": 422, "ms": int((time.perf_counter() - started) * 1000), "error": payload.get("error")})
            return 422, payload

        payload = {"error": "NO_MP4", "message": "No direct MP4 URL could be found for that Pinterest video."}
        _cache_set(url, 422, payload)
        _log_event({"route": "extract", "method": "POST", "status": 422, "ms": int((time.perf_counter() - started) * 1000), "error": payload.get("error")})
        return 422, payload

    title = info.get("title") or "Pinterest Video"
    thumbnail = info.get("thumbnail")
    payload = {"title": title, "thumbnail": thumbnail, "video_url": video_url}
    _cache_set(url, 200, payload)
    _log_event({"route": "extract", "method": "POST", "status": 200, "ms": int((time.perf_counter() - started) * 1000), "cache": "miss", "path": "yt_dlp"})
    return 200, payload


def handle_download(body: dict, client_ip: str) -> tuple[str, int, object]:
    started = time.perf_counter()

    status, payload = handle_extract(body)
    if status == 200 and isinstance(payload, dict) and payload.get("video_url"):
        return "json", 200, payload

    if not isinstance(payload, dict):
        return "json", status, payload

    stream_url = payload.get("stream_url")
    if not isinstance(stream_url, str) or not stream_url.strip():
        return "json", status, payload

    if not shutil.which("ffmpeg"):
        _log_event(
            {
                "route": "download",
                "method": "POST",
                "status": 501,
                "ms": int((time.perf_counter() - started) * 1000),
                "error": "FFMPEG_NOT_AVAILABLE",
            }
        )
        return (
            "json",
            501,
            {
                "error": "FFMPEG_NOT_AVAILABLE",
                "message": "Server-side MP4 conversion is not available on this deployment (ffmpeg missing).",
                "stream_url": stream_url,
            },
        )

    client_ip = (client_ip or "").strip()
    if client_ip and hls_mod._is_rate_limited_ip(client_ip):
        return "json", 429, {"error": "RATE_LIMITED", "message": "Too many requests. Please try again in a minute."}

    try:
        playlist = hls_mod._fetch_text(stream_url)
        duration_s = hls_mod._playlist_duration_seconds(playlist)
        if duration_s and duration_s > hls_mod._MP4_MAX_SECONDS:
            return "json", 422, {"error": "TOO_LONG", "message": "This video is too long to convert."}
    except Exception:
        pass

    mp4_path = convert_hls_to_mp4(stream_url)
    if not mp4_path:
        _log_event(
            {
                "route": "download",
                "method": "POST",
                "status": 500,
                "ms": int((time.perf_counter() - started) * 1000),
                "error": "CONVERSION_FAILED",
            }
        )
        return (
            "json",
            500,
            {
                "error": "CONVERSION_FAILED",
                "message": "Conversion failed",
                "stream_url": stream_url,
            },
        )

    title = payload.get("title") if isinstance(payload.get("title"), str) else "video"
    _log_event(
        {
            "route": "download",
            "method": "POST",
            "status": 200,
            "ms": int((time.perf_counter() - started) * 1000),
            "format": "mp4",
            "kv_rl": _kv_enabled(),
        }
    )
    return "file", 200, {"path": mp4_path, "title": title}

