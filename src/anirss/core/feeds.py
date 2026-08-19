"""RSS/Atom fetching and parsing without third-party dependencies."""

from __future__ import annotations

import hashlib
import html
import re
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from .models import AppSettings, FeedItem
from .naming import recognize_episode

MAX_FEED_BYTES = 10 * 1024 * 1024
_MAGNET_RE = re.compile(r"magnet:\?[^\s<>\"']+", re.IGNORECASE)
_TORRENT_URL_RE = re.compile(r"https?://[^\s<>\"']+?\.torrent(?:\?[^\s<>\"']*)?", re.IGNORECASE)
_HREF_RE = re.compile(r"(?:href|src)\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)


class FeedError(RuntimeError):
    """Base error for feed network and format failures."""


class FeedParseError(FeedError):
    """Raised when a document is not safe, valid RSS, or valid Atom."""


def _contains_forbidden_xml_declaration(raw: bytes) -> bool:
    """Detect DTD/entity declarations in ASCII, UTF-8, UTF-16 and UTF-32 XML."""

    if re.search(rb"<!\s*(?:doctype|entity)\b", raw, re.IGNORECASE):
        return True
    encoding: str | None = None
    if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        encoding = "utf-32"
    elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    elif raw.startswith(b"<\x00\x00\x00"):
        encoding = "utf-32-le"
    elif raw.startswith(b"\x00\x00\x00<"):
        encoding = "utf-32-be"
    elif raw.startswith(b"<\x00"):
        encoding = "utf-16-le"
    elif raw.startswith(b"\x00<"):
        encoding = "utf-16-be"
    if encoding is None:
        return False
    try:
        text = raw.decode(encoding, errors="strict")
    except UnicodeError:
        # Let ElementTree report malformed encoding below; it cannot safely be
        # considered declaration-free here.
        return True
    return bool(re.search(r"<!\s*(?:doctype|entity)\b", text, re.IGNORECASE))


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].split(":")[-1].lower()


def _children(element: ET.Element, *names: str) -> Iterable[ET.Element]:
    wanted = {name.lower() for name in names}
    return (child for child in element if _local_name(child.tag) in wanted)


def _child_text(element: ET.Element, *names: str) -> str | None:
    for child in _children(element, *names):
        value = "".join(child.itertext()).strip()
        if value:
            return value
    return None


def parse_date(value: str | None) -> datetime | None:
    """Parse RFC 822/2822 and common ISO-8601 feed timestamps."""

    if not value:
        return None
    value = value.strip()
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        parsed = None
    if parsed is None:
        normalized = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            # A few feeds publish compact offsets (+0800) and a space separator.
            for pattern in (
                "%Y-%m-%d %H:%M:%S %z",
                "%Y-%m-%dT%H:%M:%S %z",
                "%Y-%m-%d",
            ):
                try:
                    parsed = datetime.strptime(value, pattern)
                    break
                except ValueError:
                    continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _extract_candidates(
    element: ET.Element, description: str | None
) -> tuple[str | None, str | None, str | None]:
    enclosures: list[tuple[str, str | None]] = []
    links: list[str] = []
    other: list[str] = []

    for node in element.iter():
        name = _local_name(node.tag)
        href = (node.attrib.get("href") or node.attrib.get("url") or "").strip()
        rel = node.attrib.get("rel", "").lower()
        text = (node.text or "").strip()
        if name == "enclosure" and href:
            enclosures.append((href, node.attrib.get("type") or None))
        elif name == "link":
            value = href or text
            if value:
                if rel == "enclosure":
                    enclosures.append((value, node.attrib.get("type") or None))
                else:
                    links.append(value)
        elif name in {"magneturi", "torrent", "download", "contenturl"}:
            value = href or text
            if value:
                other.append(value)

    enclosure_urls = [url for url, _content_type in enclosures]
    searchable = "\n".join(other + enclosure_urls + links + ([description] if description else []))
    searchable = html.unescape(searchable)
    magnet_match = _MAGNET_RE.search(searchable)
    magnet = magnet_match.group(0).rstrip(".,);]") if magnet_match else None

    # Enclosures are explicit download metadata and take precedence over an
    # ordinary article link.  A magnet extension still wins when present.
    download_url: str | None
    content_type: str | None
    if magnet:
        download_url = magnet
        content_type = "application/x-bittorrent"
    elif enclosures:
        download_url = html.unescape(enclosures[0][0])
        content_type = enclosures[0][1]
    else:
        torrent_match = _TORRENT_URL_RE.search(searchable)
        download_url = torrent_match.group(0) if torrent_match else None
        content_type = "application/x-bittorrent" if download_url else None
        if download_url is None and description:
            for href in _HREF_RE.findall(html.unescape(description)):
                if href.startswith("magnet:?") or ".torrent" in href.lower():
                    download_url = href
                    content_type = "application/x-bittorrent"
                    break

    article_link = next((link for link in links if link != download_url), None)
    if article_link is None and links:
        article_link = links[0]
    return download_url, article_link, content_type


def parse_feed(
    data: bytes | str,
    subscription_id: int = 0,
    *,
    base_url: str | None = None,
) -> list[FeedItem]:
    """Parse RSS 2.x or Atom into normalized :class:`FeedItem` objects.

    ``subscription_id`` defaults to zero so callers may preview a feed before
    saving a subscription.  The service always supplies the real database ID.
    """

    raw = data.encode("utf-8") if isinstance(data, str) else data
    if len(raw) > MAX_FEED_BYTES:
        raise FeedParseError("feed exceeds the 10 MiB safety limit")
    # Scan the complete, size-bounded document.  Looking only at a prefix lets
    # an attacker move a DTD behind a long comment and reach ElementTree's
    # entity handling.
    if _contains_forbidden_xml_declaration(raw):
        raise FeedParseError("DTD and entity declarations are not allowed in feeds")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise FeedParseError(f"invalid feed XML: {exc}") from exc

    root_name = _local_name(root.tag)
    if root_name in {"rss", "rdf"}:
        elements = [element for element in root.iter() if _local_name(element.tag) == "item"]
    elif root_name == "feed":
        elements = [element for element in root if _local_name(element.tag) == "entry"]
    else:
        raise FeedParseError(f"unsupported feed root element: {root_name or '(empty)'}")

    items: list[FeedItem] = []
    for element in elements:
        title = _child_text(element, "title") or "Untitled"
        description = _child_text(element, "description", "summary", "content", "encoded")
        download_url, article_link, content_type = _extract_candidates(element, description)
        if base_url:
            if download_url and not download_url.lower().startswith("magnet:?"):
                download_url = urllib.parse.urljoin(base_url, download_url)
            if article_link:
                article_link = urllib.parse.urljoin(base_url, article_link)
        guid = _child_text(element, "guid", "id")
        published_at = parse_date(_child_text(element, "pubdate", "published", "updated", "date"))
        if not guid:
            material = "\x1f".join(
                (title, download_url or "", article_link or "", str(published_at or ""))
            )
            guid = "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()
        items.append(
            FeedItem(
                subscription_id=subscription_id,
                guid=guid,
                title=title,
                download_url=download_url,
                content_type=content_type,
                link=article_link,
                description=description,
                published_at=published_at,
                episode=recognize_episode(title),
            )
        )
    return items


def fetch_feed(url: str, settings: AppSettings | None = None) -> bytes:
    """Fetch one feed with size, timeout, TLS, and optional proxy controls."""

    settings = settings or AppSettings()
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise FeedError("feed URL must use HTTP or HTTPS")

    handlers: list[urllib.request.BaseHandler] = []
    if settings.proxy_url:
        handlers.append(
            urllib.request.ProxyHandler({"http": settings.proxy_url, "https": settings.proxy_url})
        )
    else:
        handlers.append(urllib.request.ProxyHandler({}))
    if parsed.scheme == "https":
        context = (
            ssl.create_default_context()
            if settings.verify_tls
            else ssl._create_unverified_context()
        )
        handlers.append(urllib.request.HTTPSHandler(context=context))

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": settings.user_agent,
            "Accept": (
                "application/atom+xml, application/rss+xml, application/xml, "
                "text/xml;q=0.9, */*;q=0.5"
            ),
        },
    )
    try:
        with urllib.request.build_opener(*handlers).open(
            request, timeout=settings.request_timeout_seconds
        ) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_FEED_BYTES:
                raise FeedError("feed exceeds the 10 MiB safety limit")
            data = response.read(MAX_FEED_BYTES + 1)
    except FeedError:
        raise
    except Exception as exc:
        raise FeedError(f"could not fetch feed: {exc}") from exc
    if len(data) > MAX_FEED_BYTES:
        raise FeedError("feed exceeds the 10 MiB safety limit")
    return data


__all__ = [
    "FeedError",
    "FeedParseError",
    "fetch_feed",
    "parse_date",
    "parse_feed",
]
