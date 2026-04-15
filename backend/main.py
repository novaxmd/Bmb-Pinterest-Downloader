import os
import re

from flask import Flask, Response, after_this_request, jsonify, request, send_file
from flask_cors import CORS

import download
import hls
import proxy

app = Flask(__name__)
CORS(app)


@app.get("/")
def root():
    return jsonify({"ok": True})


@app.post("/download")
def download_route():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        body = {}
    client_ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or (request.remote_addr or "")

    kind, status, value = download.handle_download(body, client_ip=client_ip)
    if kind == "file" and isinstance(value, dict) and isinstance(value.get("path"), str):
        path = value["path"]
        title = value.get("title") if isinstance(value.get("title"), str) else "video"
        safe_title = re.sub(r"[^A-Za-z0-9._ -]+", "", title).strip() or "video"
        download_name = f"{safe_title[:80]}.mp4"

        @after_this_request
        def _cleanup(resp):
            try:
                os.remove(path)
            except Exception:
                pass
            return resp

        return send_file(path, as_attachment=True, download_name=download_name, mimetype="video/mp4")

    if isinstance(value, dict):
        return jsonify(value), status
    return Response(value, status=status, mimetype="text/plain")


@app.post("/extract")
def extract_route():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        body = {}
    status, payload = download.handle_extract(body)
    return jsonify(payload), status


@app.get("/hls")
def hls_route():
    m3u8_url = (request.args.get("url") or "").strip()
    title = request.args.get("title") or ""
    fmt = (request.args.get("format") or "").strip().lower()
    client_ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or (request.remote_addr or "")

    status, headers, body = hls.handle_hls(m3u8_url=m3u8_url, title=title, fmt=fmt, client_ip=client_ip)
    if isinstance(body, (bytes, bytearray)):
        return Response(bytes(body), status=status, headers=headers)
    return Response(body, status=status, headers=headers)


@app.get("/proxy")
def proxy_route():
    target = (request.args.get("url") or "").strip()
    status, headers, body = proxy.handle_proxy(target)
    return Response(body, status=status, headers=headers)
