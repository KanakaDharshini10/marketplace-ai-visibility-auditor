"""Polite, read-only HTTP client.

Guardrails baked in (they are not optional flags):

* **GET and HEAD only.** No POST/PUT/PATCH/DELETE method is reachable from
  this module, so no skill in the marketplace can alter a live site.
* **No credentials.** Cookies, auth headers and client certs are never sent,
  so authenticated areas are never entered.
* **Rate limited per host** with a configurable minimum inter-request delay.
* **Byte-capped** responses and a hard per-request timeout.
* **Honest User-Agent** that identifies the auditor.
"""

from __future__ import annotations

import re
import socket
import time
import zlib
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple
from urllib import request as urlrequest
from urllib import error as urlerror
from urllib.parse import urlsplit

from .version import USER_AGENT

#: Hard ceiling on the *decompressed* size of any response body. The wire byte
#: cap (``max_bytes``) bounds what is read off the socket, but a gzip or deflate
#: stream expands, and a crafted 3 MB body can inflate to gigabytes - a
#: decompression bomb that would exhaust memory before any byte cap downstream
#: saw it. Decompression stops at this many bytes; a body that would exceed it
#: is truncated and marked, never expanded in full.
_MAX_DECOMPRESSED_BYTES = 30_000_000

#: Schemes a redirect may target. urllib's default opener also installs FTP and
#: file handlers, so without this an ``http -> ftp://internal:22/`` or a
#: ``file://`` redirect would open a socket the audit never intended. Only the
#: two web schemes are ever followed.
_REDIRECT_SCHEMES = frozenset({"http", "https"})

_META_CHARSET = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([a-zA-Z0-9_\-]+)""", re.I)
_META_CONTENT_TYPE = re.compile(
    rb"""<meta[^>]+http-equiv\s*=\s*["']?content-type["']?[^>]*content\s*=\s*["'][^"']*charset=([a-zA-Z0-9_\-]+)""",
    re.I)


@dataclass
class Response:
    """One recorded observation of one URL. This *is* the evidence."""

    requested_url: str
    final_url: str = ""
    method: str = "GET"
    status: int = 0
    reason: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    body: str = ""
    body_bytes: int = 0
    truncated: bool = False
    content_type: str = ""
    charset: str = ""
    elapsed_ms: int = 0
    redirects: List[Tuple[int, str]] = field(default_factory=list)  # (status, location)
    error: Optional[str] = None
    from_cache: bool = False
    fetched_at: float = 0.0

    # -- convenience -------------------------------------------------------
    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300 and self.error is None

    @property
    def is_html(self) -> bool:
        return "html" in (self.content_type or "").lower()

    @property
    def redirected(self) -> bool:
        return bool(self.redirects) or (
            self.final_url != "" and self.final_url != self.requested_url)

    def header(self, name: str, default: str = "") -> str:
        return self.headers.get(name.lower(), default)

    def to_dict(self, include_body: bool = False) -> dict:
        data = {
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "method": self.method,
            "status": self.status,
            "reason": self.reason,
            "content_type": self.content_type,
            "charset": self.charset,
            "body_bytes": self.body_bytes,
            "truncated": self.truncated,
            "elapsed_ms": self.elapsed_ms,
            "redirects": [{"status": s, "location": loc} for s, loc in self.redirects],
            "headers": self.headers,
            "error": self.error,
        }
        if include_body:
            data["body"] = self.body
        return data


class _RecordingRedirectHandler(urlrequest.HTTPRedirectHandler):
    """Follows redirects but records the whole chain as evidence.

    Two safety rules ride on every hop, because a redirect is the one way a
    fetch of a public URL can be steered somewhere the audit never chose:

    * a target whose scheme is not http(s) is refused, so ``file://`` and
      ``ftp://internal:22/`` redirects never reach the opener's other handlers;
    * an optional ``guard`` (wired by the evidence store) can refuse a target
      by host - a redirect into loopback, RFC 1918 space or a cloud
      metadata endpoint is refused mid-chain, not only when it happens to be
      the final URL.

    A refusal, and running past the hop limit, both raise ``URLError`` rather
    than ``HTTPError``: a redirect that never resolves is a transport failure,
    not the site answering with the last 3xx status. Reading it as a 3xx
    "answer" is how an infinite redirect loop was once recorded as a fetched
    page.
    """

    max_redirections = 6

    def __init__(self, guard: Optional[Callable[[str], Optional[str]]] = None) -> None:
        self.chain: List[Tuple[int, str]] = []
        self.guard = guard

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        scheme = urlsplit(newurl).scheme.lower()
        if scheme and scheme not in _REDIRECT_SCHEMES:
            raise urlerror.URLError(f"refused redirect to non-web scheme: {scheme}")
        if self.guard is not None:
            reason = self.guard(newurl)
            if reason:
                raise urlerror.URLError(f"refused redirect: {reason}")
        self.chain.append((int(code), newurl))
        if len(self.chain) > self.max_redirections:
            raise urlerror.URLError(
                f"too many redirects (>{self.max_redirections} hops)")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _decompress_bounded(raw: bytes, *, gzip_stream: bool) -> bytes:
    """Inflate at most ``_MAX_DECOMPRESSED_BYTES``, never the whole bomb.

    ``zlib.decompressobj().decompress(data, max_length)`` stops at the cap
    instead of allocating the full output, so a body crafted to expand without
    bound is truncated rather than exhausting memory. Truncated XML/HTML still
    parses to whatever completed before the cap, which is the honest outcome.
    """
    wbits = (16 + zlib.MAX_WBITS) if gzip_stream else zlib.MAX_WBITS
    try:
        obj = zlib.decompressobj(wbits)
        out = obj.decompress(raw, _MAX_DECOMPRESSED_BYTES)
        if not gzip_stream and not out:
            # A raw deflate stream (no zlib header) needs negative wbits.
            obj = zlib.decompressobj(-zlib.MAX_WBITS)
            out = obj.decompress(raw, _MAX_DECOMPRESSED_BYTES)
        return out
    except (OSError, zlib.error):
        return raw  # keep the raw bytes; a decode failure is itself evidence


def _decode_body(raw: bytes, headers: Dict[str, str]) -> Tuple[str, str]:
    encoding = (headers.get("content-encoding") or "").lower()
    if "gzip" in encoding:
        raw = _decompress_bounded(raw, gzip_stream=True)
    elif "deflate" in encoding:
        raw = _decompress_bounded(raw, gzip_stream=False)
    elif raw[:2] == b"\x1f\x8b":
        # A body that is a gzip stream even though no Content-Encoding header
        # said so - the usual way a `.xml.gz` sitemap is served (Content-Type
        # application/gzip, no Content-Encoding). Decoding it as text and
        # re-encoding cannot recover the original bytes, so it has to be
        # gunzipped here, from the raw bytes, before any charset handling.
        raw = _decompress_bounded(raw, gzip_stream=True)

    charset = ""
    ctype = headers.get("content-type", "")
    match = re.search(r"charset=([\w\-]+)", ctype, re.I)
    if match:
        charset = match.group(1)
    if not charset:
        head = raw[:4096]
        m2 = _META_CHARSET.search(head) or _META_CONTENT_TYPE.search(head)
        if m2:
            charset = m2.group(1).decode("ascii", "ignore")
    if not charset:
        charset = "utf-8"
    try:
        text = raw.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        charset = "utf-8"
        text = raw.decode("utf-8", errors="replace")
    return text, charset


class HttpClient:
    """Rate-limited, read-only fetcher. One instance per audit."""

    SAFE_METHODS = ("GET", "HEAD")

    def __init__(self, *, user_agent: Optional[str] = None, timeout: float = 12.0,
                 delay: float = 0.4, max_bytes: int = 3_000_000,
                 max_retries: int = 1) -> None:
        self.user_agent = user_agent or USER_AGENT
        self.timeout = timeout
        self.delay = delay
        self.max_bytes = max_bytes
        self.max_retries = max_retries
        #: Optional per-hop redirect guard: ``guard(url) -> reason | None``.
        #: The evidence store wires this to its private-host rule, so a
        #: redirect into a non-public address is refused mid-chain, not only
        #: when it is the final URL. Left ``None`` the client still refuses
        #: non-web schemes; a host guard is added on top when one is set.
        self.redirect_guard: Optional[Callable[[str], Optional[str]]] = None
        self._last_request_at: Dict[str, float] = {}
        self.request_count = 0
        self.bytes_downloaded = 0
        #: Consecutive transport failures per host, and the hosts whose circuit
        #: is open. A host that has failed to answer three times in a row is
        #: not going to answer the fourth, and the fourth attempt costs the
        #: full timeout twice over. Without this a black-holed origin spent the
        #: whole wall-clock budget discovering the same thing repeatedly, and
        #: the report could not say where the minutes had gone.
        self._consecutive_failures: Dict[str, int] = {}
        self.open_circuits: Dict[str, str] = {}
        #: Where the time went, in seconds, by outcome. Recorded so a slow
        #: zero-page run can explain itself rather than being reported as an
        #: unexplained several minutes.
        self.time_by_outcome: Dict[str, float] = {
            "answered": 0.0, "refused_or_error_status": 0.0,
            "transport_failure": 0.0, "retry_backoff": 0.0, "throttle": 0.0,
        }
        self.transport_failures = 0
        self.retries_spent = 0
        self.skipped_by_circuit = 0

    # -- politeness --------------------------------------------------------
    #: Consecutive transport failures against one host before this client
    #: stops issuing requests to it. Three is enough to tell a blip from an
    #: origin that is not answering, and it bounds the worst case at three
    #: timeouts per host rather than one per queued URL.
    CIRCUIT_THRESHOLD = 3

    def _throttle(self, host: str) -> None:
        last = self._last_request_at.get(host)
        if last is not None:
            wait = self.delay - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
                self.time_by_outcome["throttle"] += wait
        self._last_request_at[host] = time.monotonic()

    def _record_failure(self, host: str) -> None:
        count = self._consecutive_failures.get(host, 0) + 1
        self._consecutive_failures[host] = count
        self.transport_failures += 1
        if count >= self.CIRCUIT_THRESHOLD and host not in self.open_circuits:
            self.open_circuits[host] = (
                f"{count} consecutive transport failures; no further requests "
                f"were made to this host")

    def _record_success(self, host: str) -> None:
        self._consecutive_failures[host] = 0

    # -- fetching ----------------------------------------------------------
    def fetch(self, url: str, method: str = "GET", *,
              accept: str = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
              timeout: Optional[float] = None) -> Response:
        method = method.upper()
        if method not in self.SAFE_METHODS:
            raise ValueError(
                f"{method} is not permitted: this auditor is read-only "
                f"(allowed: {', '.join(self.SAFE_METHODS)})")

        host = urlsplit(url).netloc
        response = Response(requested_url=url, method=method, final_url=url)

        # A host whose circuit is open is not asked again. The answer is
        # recorded as what it is - a request this audit chose not to make -
        # so nothing downstream reads it as an observation about the site.
        if host in self.open_circuits:
            self.skipped_by_circuit += 1
            response.error = f"not attempted: {self.open_circuits[host]}"
            response.fetched_at = time.time()
            return response

        attempts = self.max_retries + 1

        for attempt in range(attempts):
            self._throttle(host)
            redirect_handler = _RecordingRedirectHandler(self.redirect_guard)
            opener = urlrequest.build_opener(redirect_handler)
            # No cookie processor and no auth handler: we never carry state.
            opener.addheaders = []
            req = urlrequest.Request(url, method=method, headers={
                "User-Agent": self.user_agent,
                "Accept": accept,
                "Accept-Encoding": "gzip, deflate",
                "Accept-Language": "en;q=0.9,*;q=0.5",
                "Connection": "close",
            })
            started = time.monotonic()
            try:
                self.request_count += 1
                with opener.open(req, timeout=timeout or self.timeout) as handle:
                    raw = handle.read(self.max_bytes + 1) if method == "GET" else b""
                    response.status = handle.status
                    response.reason = handle.reason or ""
                    response.headers = {k.lower(): v for k, v in handle.headers.items()}
                    response.final_url = handle.geturl()
            except urlerror.HTTPError as exc:  # 4xx / 5xx still carry evidence
                raw = b""
                try:
                    raw = exc.read(self.max_bytes + 1) if method == "GET" else b""
                except Exception:  # pragma: no cover - defensive
                    raw = b""
                response.status = int(exc.code)
                response.reason = str(exc.reason or "")
                response.headers = {k.lower(): v for k, v in (exc.headers or {}).items()}
                response.final_url = exc.url or url
            except (urlerror.URLError, socket.timeout, ConnectionError, OSError) as exc:
                spent = time.monotonic() - started
                self.time_by_outcome["transport_failure"] += spent
                response.error = f"{type(exc).__name__}: {exc}"
                response.elapsed_ms = int(spent * 1000)
                response.redirects = list(redirect_handler.chain)
                response.fetched_at = time.time()
                if attempt + 1 < attempts:
                    pause = min(1.5, self.delay * 2)
                    time.sleep(pause)
                    self.time_by_outcome["retry_backoff"] += pause
                    self.retries_spent += 1
                    continue
                self._record_failure(host)
                return response
            except Exception as exc:  # pragma: no cover - never crash an audit
                response.error = f"{type(exc).__name__}: {exc}"
                response.fetched_at = time.time()
                return response

            spent = time.monotonic() - started
            response.elapsed_ms = int(spent * 1000)
            response.redirects = list(redirect_handler.chain)
            response.fetched_at = time.time()
            # The origin answered, whatever it said. A 403 is an answer.
            self._record_success(host)
            self.time_by_outcome["answered" if response.status < 400
                                 else "refused_or_error_status"] += spent
            if len(raw) > self.max_bytes:
                response.truncated = True
                raw = raw[: self.max_bytes]
            response.body_bytes = len(raw)
            self.bytes_downloaded += len(raw)
            response.content_type = (
                response.headers.get("content-type", "").split(";")[0].strip().lower())
            if raw:
                response.body, response.charset = _decode_body(raw, response.headers)
            # Retry once on a transient upstream failure.
            if response.status in (429, 502, 503, 504) and attempt + 1 < attempts:
                retry_after = response.headers.get("retry-after")
                pause = 2.0
                if retry_after and retry_after.isdigit():
                    pause = min(5.0, float(retry_after))
                time.sleep(pause)
                self.time_by_outcome["retry_backoff"] += pause
                self.retries_spent += 1
                continue
            return response

        return response

    def head_or_get(self, url: str) -> Response:
        """HEAD first (cheapest); fall back to GET when HEAD is unsupported."""
        response = self.fetch(url, method="HEAD")
        if response.error or response.status in (0, 403, 405, 501):
            return self.fetch(url, method="GET")
        return response


def read_gzip_maybe(data: bytes) -> bytes:
    """Transparently gunzip sitemap payloads served as ``.xml.gz``.

    Bounded to ``_MAX_DECOMPRESSED_BYTES`` so a gzipped sitemap cannot be a
    decompression bomb any more than a gzipped page can.
    """
    if data[:2] == b"\x1f\x8b":
        return _decompress_bounded(data, gzip_stream=True)
    return data
