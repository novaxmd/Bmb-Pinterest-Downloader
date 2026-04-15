import re
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

def _now_ms() -> int:
    return int(time.time() * 1000)


def _log_event(event: dict):
    try:
        event.setdefault("ts_ms", _now_ms())
        print(json.dumps(event, ensure_ascii=False))
    except Exception:
        return


def _is_allowed_target(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if host == "pinimg.com" or host.endswith(".pinimg.com"):
        return True
    if host == "pinterest.com" or host.endswith(".pinterest.com"):
        return True
    return False


def _guess_content_type(path: str) -> str:
    p = (path or "").lower()
    if p.endswith(".m3u8"):
        return "application/vnd.apple.mpegurl"
    if p.endswith(".ts"):
        return "video/mp2t"
    if p.endswith(".mp4"):
        return "video/mp4"
    if p.endswith(".jpg") or p.endswith(".jpeg"):
        return "image/jpeg"
    if p.endswith(".png"):
        return "image/png"
    if p.endswith(".webp"):
        return "image/webp"
    if p.endswith(".gif"):
        return "image/gif"
    return "application/octet-stream"


def handle_proxy(target: str) -> tuple[int, dict, bytes]:
    started = time.perf_counter()
    target = (target or "").strip()

    if not target:
        _log_event({"route": "proxy", "method": "GET", "status": 400, "ms": int((time.perf_counter() - started) * 1000), "error": "MISSING_URL"})
        return 400, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}, b"Missing url"

    if not _is_allowed_target(target):
        _log_event({"route": "proxy", "method": "GET", "status": 403, "ms": int((time.perf_counter() - started) * 1000), "error": "BLOCKED", "host": (urlparse(target).hostname or "").lower()})
        return 403, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}, b"Blocked url"

    try:
        req = Request(
            target,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
            },
            method="GET",
        )
        with urlopen(req, timeout=25) as resp:
            body = resp.read()
            content_type = resp.headers.get("Content-Type") or ""
            if not content_type:
                content_type = _guess_content_type(urlparse(target).path)
            content_type = re.sub(r"\s+", " ", content_type).strip()

        headers = {
            "Content-Type": content_type,
            "Cache-Control": "public, max-age=3600, immutable",
            "Access-Control-Allow-Origin": "*",
            "Cross-Origin-Resource-Policy": "cross-origin",
        }
        _log_event({"route": "proxy", "method": "GET", "status": 200, "ms": int((time.perf_counter() - started) * 1000), "host": (urlparse(target).hostname or "").lower()})
        return 200, headers, body
    except HTTPError as e:
        status = int(e.code or 502)
        _log_event({"route": "proxy", "method": "GET", "status": status, "ms": int((time.perf_counter() - started) * 1000), "error": "UPSTREAM_HTTP_ERROR"})
        return status, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}, b"Upstream error"
    except URLError:
        _log_event({"route": "proxy", "method": "GET", "status": 502, "ms": int((time.perf_counter() - started) * 1000), "error": "UPSTREAM_URL_ERROR"})
        return 502, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}, b"Upstream error"
    except Exception:
        _log_event({"route": "proxy", "method": "GET", "status": 500, "ms": int((time.perf_counter() - started) * 1000), "error": "PROXY_ERROR"})
        return 500, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}, b"Proxy error"
