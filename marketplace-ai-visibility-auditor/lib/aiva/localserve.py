"""A throwaway local HTTP server for the bundled fixture sites.

Used by ``run_audit.py --offline`` and by the test-suite so the audit can be
demonstrated and regression-tested end to end, over real HTTP, with no network
access and no third-party site involved.

Fixture files may contain date placeholders (``{{TODAY}}``, ``{{STALE}}`` ...)
which are substituted at serve time. That keeps the "strong" fixture
permanently fresh and the "weak" fixture permanently stale, so freshness rules
stay testable however long after authoring the suite is run.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import email.utils
import http.server
import os
import socketserver
import threading
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple

TEMPLATE_SUFFIXES = {".html", ".htm", ".xml", ".txt", ".json"}

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".xml": "application/xml; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
}


def substitutions(now: Optional[_dt.datetime] = None) -> Dict[str, str]:
    now = now or _dt.datetime.now(_dt.timezone.utc)
    day = _dt.timedelta(days=1)
    return {
        "{{NOW_ISO}}": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "{{TODAY}}": now.strftime("%Y-%m-%d"),
        "{{RECENT}}": (now - 7 * day).strftime("%Y-%m-%d"),
        "{{RECENT_ISO}}": (now - 7 * day).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "{{MONTH_AGO}}": (now - 30 * day).strftime("%Y-%m-%d"),
        "{{STALE}}": (now - 900 * day).strftime("%Y-%m-%d"),
        "{{STALE_ISO}}": (now - 900 * day).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "{{VERY_STALE}}": (now - 1500 * day).strftime("%Y-%m-%d"),
        "{{YEAR}}": str(now.year),
        "{{OLD_YEAR}}": str(now.year - 7),
        "{{NEXT_YEAR_END}}": f"{now.year + 1}-12-31",
    }


#: A fixture directory may ship `_redirects.json` mapping a request path to
#: ``[status, location]`` so redirect chains, retired URLs and home-page
#: catch-alls can be regression-tested without a real web server.
REDIRECT_FILE = "_redirects.json"

#: ...and `_responses.json` mapping a request path to ``{"status": int,
#: "delay_s": float, "body": str}`` so refusals (403, 429), server errors
#: and timeouts can be regression-tested too. A delay longer than the
#: auditor's request timeout is how a timeout is simulated.
RESPONSE_FILE = "_responses.json"


class _Handler(http.server.BaseHTTPRequestHandler):
    directory = "."
    soft_404 = False
    redirects: Dict[str, list] = {}
    responses: Dict[str, dict] = {}
    server_version = "aiva-fixture/1.0"

    def log_message(self, fmt, *args):  # noqa: D102 - keep test output clean
        return

    # -- helpers -----------------------------------------------------------
    def _resolve(self, path: str) -> Optional[Path]:
        clean = path.split("?", 1)[0].split("#", 1)[0]
        clean = clean.lstrip("/")
        base = Path(self.directory).resolve()
        target = (base / clean).resolve()
        if base != target and base not in target.parents:
            return None  # path traversal attempt
        if target.is_dir():
            target = target / "index.html"
        return target if target.is_file() else None

    def _render(self, target: Path) -> bytes:
        raw = target.read_bytes()
        if target.suffix.lower() in TEMPLATE_SUFFIXES:
            text = raw.decode("utf-8", "replace")
            for token, value in substitutions().items():
                text = text.replace(token, value)
            raw = text.encode("utf-8")
        return raw

    def _respond(self, status: int, body: bytes, target: Optional[Path],
                 head_only: bool = False) -> None:
        self.send_response(status)
        suffix = target.suffix.lower() if target else ".html"
        self.send_header("Content-Type", CONTENT_TYPES.get(suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        if target is not None:
            stamp = os.stat(target).st_mtime
            self.send_header("Last-Modified", email.utils.formatdate(stamp, usegmt=True))
        self.send_header("X-Fixture", "aiva")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _serve(self, head_only: bool) -> None:
        route = self.path.split("?", 1)[0]
        if route in self.responses:
            spec = self.responses[route] or {}
            delay = float(spec.get("delay_s") or 0)
            if delay > 0:
                import time
                time.sleep(delay)
            status = int(spec.get("status") or 200)
            body = str(spec.get("body") or f"<!doctype html><title>{status}</title>"
                                            f"<h1>{status}</h1>").encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            for name, value in (spec.get("headers") or {}).items():
                self.send_header(str(name), str(value))
            self.end_headers()
            if not head_only:
                self.wfile.write(body)
            return
        if route in self.redirects:
            status, location = self.redirects[route]
            self.send_response(int(status))
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if Path(route).name.startswith("_"):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        target = self._resolve(self.path)
        if target is None:
            if self.soft_404:
                index = Path(self.directory) / "index.html"
                if index.is_file():
                    self._respond(200, self._render(index), index, head_only)
                    return
            body = b"<!doctype html><title>Not found</title><h1>404 Not found</h1>"
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not head_only:
                self.wfile.write(body)
            return
        self._respond(200, self._render(target), target, head_only)

    # -- verbs -------------------------------------------------------------
    def do_GET(self):  # noqa: N802
        self._serve(head_only=False)

    def do_HEAD(self):  # noqa: N802
        self._serve(head_only=True)


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def start(directory: Path, *, soft_404: bool = False,
          host: str = "127.0.0.1", port: int = 0) -> Tuple[_Server, str]:
    """Start a background server and return ``(server, base_url)``."""
    directory = Path(directory).resolve()
    if not directory.is_dir():
        raise FileNotFoundError(f"fixture directory not found: {directory}")
    import json
    redirects: Dict[str, list] = {}
    redirect_file = directory / REDIRECT_FILE
    if redirect_file.is_file():
        redirects = json.loads(redirect_file.read_text(encoding="utf-8"))
    responses: Dict[str, dict] = {}
    response_file = directory / RESPONSE_FILE
    if response_file.is_file():
        responses = json.loads(response_file.read_text(encoding="utf-8"))
    handler_cls = type("_FixtureHandler", (_Handler,),
                       {"directory": str(directory), "soft_404": soft_404,
                        "redirects": redirects, "responses": responses})
    server = _Server((host, port), handler_cls)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    actual_host, actual_port = server.server_address[:2]
    return server, f"http://{actual_host}:{actual_port}"


@contextlib.contextmanager
def serving(directory: Path, *, soft_404: bool = False) -> Iterator[str]:
    server, base_url = start(directory, soft_404=soft_404)
    try:
        yield base_url
    finally:
        server.shutdown()
        server.server_close()
