"""Shared urllib/TLS helpers for AniRSS network clients."""

from __future__ import annotations

import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to http(s), never downgrading https to http.

    urllib's default redirect handling happily follows a feed or download
    URL onto ``ftp`` or from TLS onto plaintext.  Both silently defeat the
    scheme validation done on the original URL, so refuse them instead.
    """

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        target = urllib.parse.urlsplit(newurl)
        if target.scheme not in {"http", "https"}:
            raise urllib.error.HTTPError(
                newurl,
                code,
                f"redirect to unsupported scheme {target.scheme!r} refused",
                headers,
                fp,
            )
        source = urllib.parse.urlsplit(req.full_url)
        if source.scheme == "https" and target.scheme == "http":
            raise urllib.error.HTTPError(
                newurl,
                code,
                "redirect from https to http refused",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def tls_context(*, verify: bool) -> ssl.SSLContext:
    """Return a default TLS context, optionally with verification disabled."""

    context = ssl.create_default_context()
    if not verify:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


__all__ = ["SafeRedirectHandler", "tls_context"]
