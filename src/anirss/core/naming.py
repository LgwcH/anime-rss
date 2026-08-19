"""Episode recognition and cross-platform safe download paths."""

from __future__ import annotations

import re
import unicodedata
import urllib.parse
from pathlib import Path

from .models import FeedItem, Subscription

_INVALID_COMPONENT = re.compile(r"[<>:\"/\\|?*\x00-\x1f\x7f]+")
_WHITESPACE = re.compile(r"\s+")
_REPLACEMENTS = re.compile(r"[_-]{3,}")
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class UnsafePathError(ValueError):
    """Raised when a constructed download path escapes its configured root."""


def sanitize_component(value: str, *, fallback: str = "Untitled", max_length: int = 180) -> str:
    """Return one portable filesystem component, never a path.

    The result is valid on Windows, macOS, and common Linux filesystems.  It
    removes path separators, control characters, trailing dots/spaces, and
    Windows device names while preserving useful CJK characters.
    """

    if max_length < 8:
        raise ValueError("max_length must be at least 8")
    value = unicodedata.normalize("NFKC", str(value))
    value = _INVALID_COMPONENT.sub("_", value)
    value = _WHITESPACE.sub(" ", value).strip(" .")
    value = _REPLACEMENTS.sub("_", value)
    if value in {"", ".", ".."}:
        value = fallback
    suffix = Path(value).suffix
    stem = value[: -len(suffix)] if suffix else value
    if stem.upper() in _WINDOWS_RESERVED:
        value = "_" + value
    if len(value) > max_length:
        suffix = Path(value).suffix[:20]
        keep = max_length - len(suffix)
        value = value[:keep].rstrip(" .") + suffix
    return value or fallback


_EPISODE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bS(?P<season>\d{1,3})\s*[. _-]*E(?P<episode>\d{1,4}(?:\.\d+)?)\b", re.I),
    re.compile(r"(?:第\s*)?(?P<episode>\d{1,4}(?:\.\d+)?)\s*(?:话|話|集)\b", re.I),
    re.compile(r"\b(?:EP(?:ISODE)?|E)\s*[. _-]*(?P<episode>\d{1,4}(?:\.\d+)?(?:v\d+)?)\b", re.I),
    re.compile(r"\[\s*(?P<episode>\d{1,3}(?:\.\d+)?(?:v\d+)?)\s*\]", re.I),
    re.compile(r"(?:^|\s)-\s*(?P<episode>\d{1,3}(?:\.\d+)?(?:v\d+)?)\s*(?:\[|\(|$)", re.I),
)


def recognize_episode(title: str, pattern: str | None = None) -> str | None:
    """Extract an episode label from common English/Japanese/Chinese titles.

    A subscription may provide a custom regular expression.  A named
    ``episode`` group is preferred, followed by the first capture group.
    """

    if pattern:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            if "episode" in match.groupdict():
                return match.group("episode")
            if match.lastindex:
                return match.group(1)
            return match.group(0)
        return None

    for expression in _EPISODE_PATTERNS:
        match = expression.search(title)
        if not match:
            continue
        episode = match.group("episode")
        # Resolution tags and years are far more likely than episode numbers.
        numeric = re.match(r"\d+", episode)
        if numeric and int(numeric.group(0)) in {360, 480, 720, 1080, 1440, 2160, 4320}:
            continue
        season = match.groupdict().get("season")
        return f"S{int(season):02d}E{episode}" if season is not None else episode
    return None


def ensure_within_root(root: str | Path, candidate: str | Path) -> Path:
    """Resolve and validate a path against a trusted root."""

    resolved_root = Path(root).expanduser().resolve()
    resolved_candidate = Path(candidate).expanduser().resolve()
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise UnsafePathError(
            f"path {resolved_candidate} is outside download root {resolved_root}"
        ) from exc
    return resolved_candidate


def create_series_directory(root: str | Path, series_name: str) -> Path:
    """Create a safely named, root-contained directory for one subscription."""

    resolved_root = Path(root).expanduser().resolve()
    resolved_root.mkdir(parents=True, exist_ok=True)
    component = sanitize_component(series_name, fallback="Anime")
    candidate = ensure_within_root(resolved_root, resolved_root / component)
    candidate.mkdir(parents=False, exist_ok=True)
    # Re-resolve after creation to catch a pre-existing symlink/junction.
    return ensure_within_root(resolved_root, candidate)


def safe_download_path(directory: str | Path, filename: str) -> Path:
    """Build a file path that cannot escape ``directory``."""

    resolved_directory = Path(directory).expanduser().resolve()
    cleaned = sanitize_component(filename, fallback="download")
    candidate = ensure_within_root(resolved_directory, resolved_directory / cleaned)
    if candidate == resolved_directory:
        raise UnsafePathError("download target must be a file below its directory")
    return candidate


def filename_for_item(item: FeedItem, *, max_length: int = 220) -> str:
    """Derive a title-based filename while keeping a useful URL extension."""

    source_name = ""
    if item.download_url and not item.download_url.lower().startswith("magnet:"):
        parsed = urllib.parse.urlsplit(item.download_url)
        source_name = urllib.parse.unquote(Path(parsed.path).name)
    source_suffix = Path(source_name).suffix
    title_suffix = Path(item.title).suffix.lower()
    known_suffixes = {
        ".mkv",
        ".mp4",
        ".avi",
        ".mov",
        ".webm",
        ".m4v",
        ".ts",
        ".torrent",
        ".zip",
        ".7z",
    }
    if title_suffix in known_suffixes:
        candidate = item.title
    elif source_suffix:
        candidate = item.title + source_suffix
    else:
        candidate = item.title
    return sanitize_component(candidate, fallback="download", max_length=max_length)


class NamingPolicy:
    """Central naming policy shared by the service and downloaders."""

    def __init__(self, download_root: str | Path) -> None:
        self.download_root = Path(download_root).expanduser()

    def directory_for(self, subscription: Subscription, *, create: bool = True) -> Path:
        if subscription.save_directory:
            explicit = Path(subscription.save_directory).expanduser()
            if not explicit.is_absolute():
                raise UnsafePathError("a subscription save_directory must be an absolute path")
            explicit = explicit.resolve()
            if create:
                explicit.mkdir(parents=True, exist_ok=True)
            if not explicit.is_dir() and create:
                raise UnsafePathError("subscription save_directory is not a directory")
            return explicit
        label = subscription.directory_name or subscription.name
        if create:
            return create_series_directory(self.download_root, label)
        root = self.download_root.resolve()
        return ensure_within_root(root, root / sanitize_component(label, fallback="Anime"))

    def filename_for(self, item: FeedItem) -> str:
        return filename_for_item(item)

    def path_for(self, subscription: Subscription, item: FeedItem) -> Path:
        directory = self.directory_for(subscription)
        return safe_download_path(directory, self.filename_for(item))


__all__ = [
    "NamingPolicy",
    "UnsafePathError",
    "create_series_directory",
    "ensure_within_root",
    "filename_for_item",
    "recognize_episode",
    "safe_download_path",
    "sanitize_component",
]
