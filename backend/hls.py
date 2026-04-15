import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen


_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

_UPSTASH_REDIS_REST_URL = (os.environ.get("UPSTASH_REDIS_REST_URL") or "").strip()
_UPSTASH_REDIS_REST_TOKEN = (os.environ.get("UPSTASH_REDIS_REST_TOKEN") or "").strip()
_MP4_MAX_SECONDS = 300.0
_MP4_RATE_LIMIT_PER_MINUTE = 6


def _safe_filename(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return "pinterest-video"
    value = re.sub(r"[^\w\s\-\(\)\[\]\.]", "", value, flags=re.UNICODE)
    value = re.sub(r"\s+", " ", value).strip()
    value = value[:80].strip()
    return value or "pinterest-video"


def _safe_ascii_filename(value: str) -> str:
    value = _safe_filename(value)
    value = value.encode("ascii", errors="ignore").decode("ascii")
    value = re.sub(r"[^A-Za-z0-9\s\-\(\)\[\]\.]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = value[:80].strip()
    return value or "pinterest-video"


def _content_disposition(filename: str, filename_utf8: str, ext: str) -> str:
    safe_ascii = _safe_ascii_filename(filename)
    safe_utf8 = _safe_filename(filename_utf8)
    ext = (ext or "ts").lstrip(".")
    encoded = quote(f"{safe_utf8}.{ext}", safe="")
    return f'attachment; filename="{safe_ascii}.{ext}"; filename*=UTF-8\'\'{encoded}'


def _is_allowed_m3u8(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("https", "http"):
        return False
    host = (parsed.hostname or "").lower()
    if not host.endswith(".pinimg.com") and host != "pinimg.com":
        return False
    if not parsed.path.lower().endswith(".m3u8"):
        return False
    return True


def _fetch_text(url: str) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/vnd.apple.mpegurl,application/x-mpegurl,text/plain,*/*",
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


def _rate_limit_key(ip: str) -> str:
    digest = hashlib.sha256(ip.encode("utf-8")).hexdigest()
    minute_bucket = int(time.time() // 60)
    return f"rl:hlsmp4:{minute_bucket}:{digest}"


def _is_rate_limited_ip(ip: str) -> bool:
    if not _kv_enabled():
        return False
    ip = (ip or "").strip()
    if not ip:
        return False
    key = _rate_limit_key(ip)
    try:
        incr = _kv_command(["INCR", key])
        count = incr.get("result") if isinstance(incr, dict) else None
        if isinstance(count, int) and count == 1:
            _kv_command(["EXPIRE", key, 70])
        if isinstance(count, int) and count > _MP4_RATE_LIMIT_PER_MINUTE:
            return True
    except Exception:
        return False
    return False


def _playlist_duration_seconds(playlist: str) -> float:
    total = 0.0
    for line in (playlist or "").splitlines():
        line = (line or "").strip()
        if not line.startswith("#EXTINF:"):
            continue
        raw = line.split(":", 1)[1] if ":" in line else ""
        raw = raw.split(",", 1)[0].strip()
        try:
            total += float(raw)
        except Exception:
            continue
    return total


def _iter_segments(m3u8_url: str, playlist: str):
    for line in playlist.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().endswith(".m3u8"):
            continue
        yield urljoin(m3u8_url, line)


def _pick_variant_playlist(master_url: str, playlist: str) -> str:
    lines = [l.strip() for l in playlist.splitlines()]
    variants = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXT-X-STREAM-INF"):
            attrs = line.split(":", 1)[1] if ":" in line else ""
            bandwidth = 0
            for part in attrs.split(","):
                part = part.strip()
                if part.upper().startswith("BANDWIDTH="):
                    try:
                        bandwidth = int(part.split("=", 1)[1].strip())
                    except Exception:
                        bandwidth = 0
                    break
            j = i + 1
            while j < len(lines) and (not lines[j] or lines[j].startswith("#")):
                j += 1
            if j < len(lines):
                uri = lines[j]
                variants.append((bandwidth, urljoin(master_url, uri)))
                i = j
        i += 1
    if not variants:
        return ""
    variants.sort(key=lambda x: x[0], reverse=True)
    return variants[0][1]


def handle_hls(m3u8_url: str, title: str, fmt: str, client_ip: str) -> tuple[int, dict, object]:
    started = time.perf_counter()

    m3u8_url = (m3u8_url or "").strip()
    title = title or ""
    fmt = (fmt or "").strip().lower()

    if not m3u8_url:
        _log_event({"route": "hls", "method": "GET", "status": 400, "ms": int((time.perf_counter() - started) * 1000), "error": "MISSING_URL"})
        return 400, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}, b"Missing url"

    if not _is_allowed_m3u8(m3u8_url):
        _log_event({"route": "hls", "method": "GET", "status": 400, "ms": int((time.perf_counter() - started) * 1000), "error": "INVALID_HLS_URL"})
        return 400, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}, b"Invalid HLS URL"

    try:
        playlist = _fetch_text(m3u8_url)
    except (HTTPError, URLError):
        _log_event({"route": "hls", "method": "GET", "status": 502, "ms": int((time.perf_counter() - started) * 1000), "error": "PLAYLIST_FETCH_FAILED"})
        return 502, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}, b"Failed to fetch playlist"
    except Exception:
        _log_event({"route": "hls", "method": "GET", "status": 500, "ms": int((time.perf_counter() - started) * 1000), "error": "PLAYLIST_FETCH_ERROR"})
        return 500, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}, b"Unexpected server error"

    if "#EXT-X-KEY" in playlist:
        _log_event({"route": "hls", "method": "GET", "status": 422, "ms": int((time.perf_counter() - started) * 1000), "error": "ENCRYPTED_HLS"})
        return 422, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}, b"Encrypted HLS is not supported"

    for _ in range(3):
        if "#EXT-X-STREAM-INF" not in playlist:
            break
        next_url = _pick_variant_playlist(m3u8_url, playlist)
        if not next_url:
            break
        m3u8_url = next_url
        try:
            playlist = _fetch_text(m3u8_url)
        except (HTTPError, URLError):
            _log_event({"route": "hls", "method": "GET", "status": 502, "ms": int((time.perf_counter() - started) * 1000), "error": "VARIANT_FETCH_FAILED"})
            return 502, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}, b"Failed to fetch variant playlist"
        except Exception:
            _log_event({"route": "hls", "method": "GET", "status": 500, "ms": int((time.perf_counter() - started) * 1000), "error": "VARIANT_FETCH_ERROR"})
            return 500, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}, b"Unexpected server error"
        if "#EXT-X-KEY" in playlist:
            _log_event({"route": "hls", "method": "GET", "status": 422, "ms": int((time.perf_counter() - started) * 1000), "error": "ENCRYPTED_HLS"})
            return 422, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}, b"Encrypted HLS is not supported"

    segments = list(_iter_segments(m3u8_url, playlist))
    if not segments:
        _log_event({"route": "hls", "method": "GET", "status": 422, "ms": int((time.perf_counter() - started) * 1000), "error": "NO_SEGMENTS"})
        return 422, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}, b"No segments found"

    if len(segments) > 400:
        _log_event({"route": "hls", "method": "GET", "status": 422, "ms": int((time.perf_counter() - started) * 1000), "error": "TOO_MANY_SEGMENTS", "segments": len(segments)})
        return 422, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}, b"Too many segments"

    wants_mp4 = fmt == "mp4"
    duration_s = _playlist_duration_seconds(playlist)

    if wants_mp4 and duration_s and duration_s > _MP4_MAX_SECONDS:
        _log_event({"route": "hls", "method": "GET", "status": 422, "ms": int((time.perf_counter() - started) * 1000), "error": "TOO_LONG", "duration_s": round(duration_s, 3)})
        return 422, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}, b"Too long"

    if wants_mp4 and _is_rate_limited_ip(client_ip):
        _log_event({"route": "hls", "method": "GET", "status": 429, "ms": int((time.perf_counter() - started) * 1000), "error": "RATE_LIMITED"})
        return 429, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}, b"Rate limited"

    ext = "mp4" if wants_mp4 else "ts"
    disposition = _content_disposition(title, title, ext)

    if wants_mp4 and not shutil.which("ffmpeg"):
        _log_event({"route": "hls", "method": "GET", "status": 501, "ms": int((time.perf_counter() - started) * 1000), "error": "FFMPEG_NOT_AVAILABLE"})
        return 501, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}, b"Server-side MP4 conversion is not available on this deployment."

    if not wants_mp4:
        headers = {
            "Content-Type": "video/mp2t",
            "Content-Disposition": disposition,
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
            "Cross-Origin-Resource-Policy": "cross-origin",
        }

        def _gen_ts():
            try:
                for seg_url in segments:
                    req = Request(seg_url, headers={"User-Agent": _USER_AGENT}, method="GET")
                    with urlopen(req, timeout=30) as resp:
                        while True:
                            chunk = resp.read(1024 * 128)
                            if not chunk:
                                break
                            yield chunk
            finally:
                _log_event({"route": "hls", "method": "GET", "status": 200, "ms": int((time.perf_counter() - started) * 1000), "format": "ts", "segments": len(segments), "duration_s": round(duration_s, 3)})

        return 200, headers, _gen_ts()

    try:
        proc = subprocess.Popen(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-c",
                "copy",
                "-bsf:a",
                "aac_adtstoasc",
                "-movflags",
                "frag_keyframe+empty_moov+default_base_moof",
                "-f",
                "mp4",
                "pipe:1",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
    except Exception:
        _log_event({"route": "hls", "method": "GET", "status": 500, "ms": int((time.perf_counter() - started) * 1000), "error": "FFMPEG_START_FAILED"})
        return 500, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}, b"Failed to start MP4 converter."

    headers = {
        "Content-Type": "video/mp4",
        "Content-Disposition": disposition,
        "Cache-Control": "no-store",
        "Access-Control-Allow-Origin": "*",
        "Cross-Origin-Resource-Policy": "cross-origin",
    }

    def _feed_stdin():
        try:
            for seg_url in segments:
                req = Request(seg_url, headers={"User-Agent": _USER_AGENT}, method="GET")
                with urlopen(req, timeout=30) as resp:
                    while True:
                        chunk = resp.read(1024 * 128)
                        if not chunk:
                            break
                        if proc.stdin:
                            proc.stdin.write(chunk)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        finally:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:
                pass

    feeder = threading.Thread(target=_feed_stdin, daemon=True)
    feeder.start()

    def _gen_mp4():
        try:
            stdout = proc.stdout
            if not stdout:
                return
            while True:
                chunk = stdout.read(1024 * 128)
                if not chunk:
                    break
                yield chunk
        finally:
            try:
                proc.wait(timeout=30)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            try:
                feeder.join(timeout=2)
            except Exception:
                pass
            _log_event({"route": "hls", "method": "GET", "status": 200, "ms": int((time.perf_counter() - started) * 1000), "format": "mp4", "segments": len(segments), "duration_s": round(duration_s, 3), "kv_rl": _kv_enabled()})

    return 200, headers, _gen_mp4()
