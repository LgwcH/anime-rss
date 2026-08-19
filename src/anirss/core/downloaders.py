"""Built-in HTTP downloader and optional, lazily loaded libtorrent adapter."""

from __future__ import annotations

import importlib
import re
import ssl
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from .models import AppSettings, DownloadKind, DownloadTask
from .naming import ensure_within_root, safe_download_path

ProgressCallback = Callable[[int, int | None, float], None]
MAX_TORRENT_METADATA_BYTES = 20 * 1024 * 1024


class DownloadError(RuntimeError):
    pass


class DownloadCancelled(DownloadError):
    pass


class LibtorrentUnavailableError(DownloadError):
    pass


@dataclass(slots=True, frozen=True)
class DownloadResult:
    path: Path
    downloaded_bytes: int
    total_bytes: int | None


class _LibtorrentSession(Protocol):
    def apply_settings(self, settings: dict[str, object]) -> None: ...

    def listen_on(self, start_port: int, end_port: int) -> None: ...


class DownloadControl:
    """Cooperative, thread-safe pause and cancellation primitive."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._resumed = threading.Event()
        self._resumed.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def paused(self) -> bool:
        return not self._resumed.is_set()

    def pause(self) -> None:
        self._resumed.clear()

    def resume(self) -> None:
        self._resumed.set()

    def cancel(self) -> None:
        self._cancelled.set()
        self._resumed.set()

    def checkpoint(self, timeout: float = 0.25) -> None:
        while not self._resumed.wait(timeout):
            if self.cancelled:
                raise DownloadCancelled("download was cancelled")
        if self.cancelled:
            raise DownloadCancelled("download was cancelled")


class Downloader(Protocol):
    def download(
        self,
        task: DownloadTask,
        settings: AppSettings,
        control: DownloadControl,
        progress_callback: ProgressCallback | None = None,
    ) -> DownloadResult: ...


def classify_download(source_url: str, content_type: str | None = None) -> DownloadKind:
    if source_url.lower().startswith("magnet:?"):
        return DownloadKind.MAGNET
    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized_type in {
        "application/x-bittorrent",
        "application/bittorrent",
    }:
        return DownloadKind.TORRENT
    path = urllib.parse.urlsplit(source_url).path.lower()
    if path.endswith(".torrent"):
        return DownloadKind.TORRENT
    return DownloadKind.HTTP


class HttpDownloader:
    """Streaming downloader with resume, atomic completion, and TLS controls."""

    chunk_size = 256 * 1024

    def download(
        self,
        task: DownloadTask,
        settings: AppSettings,
        control: DownloadControl,
        progress_callback: ProgressCallback | None = None,
    ) -> DownloadResult:
        parsed = urllib.parse.urlsplit(task.source_url)
        if parsed.scheme not in {"http", "https"}:
            raise DownloadError("HTTP downloads require an http:// or https:// URL")

        directory = Path(task.destination_directory).expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        target = safe_download_path(directory, task.filename)
        partial = ensure_within_root(directory, target.with_name(target.name + ".part"))

        if target.exists() and not settings.overwrite_existing:
            size = target.stat().st_size
            if task.total_bytes is not None and size != task.total_bytes:
                raise DownloadError(
                    "an existing target has a different size; choose overwrite "
                    "or remove the conflicting file"
                )
            if progress_callback:
                progress_callback(size, size, 1.0)
            return DownloadResult(target, size, size)
        if not settings.keep_partial_downloads and partial.exists():
            partial.unlink()
        existing = partial.stat().st_size if partial.exists() else 0

        headers = {"User-Agent": settings.user_agent, "Accept": "*/*"}
        if existing:
            headers["Range"] = f"bytes={existing}-"
        request = urllib.request.Request(task.source_url, headers=headers)
        handlers: list[urllib.request.BaseHandler] = []
        handlers.append(
            urllib.request.ProxyHandler(
                {"http": settings.proxy_url, "https": settings.proxy_url}
                if settings.proxy_url
                else {}
            )
        )
        if parsed.scheme == "https":
            context = (
                ssl.create_default_context()
                if settings.verify_tls
                else ssl._create_unverified_context()
            )
            handlers.append(urllib.request.HTTPSHandler(context=context))

        try:
            control.checkpoint()
            with urllib.request.build_opener(*handlers).open(
                request, timeout=settings.request_timeout_seconds
            ) as response:
                status = getattr(response, "status", response.getcode())
                length_header = response.headers.get("Content-Length")
                response_length = int(length_header) if length_header else None
                if response_length is not None and response_length < 0:
                    raise DownloadError("server returned a negative Content-Length")

                resumed = False
                total: int | None
                if status == 206:
                    content_range = response.headers.get("Content-Range", "").strip()
                    match = re.fullmatch(
                        r"bytes\s+(\d+)-(\d+)/(\d+)",
                        content_range,
                        flags=re.IGNORECASE,
                    )
                    if match is None:
                        raise DownloadError(
                            "server returned an invalid Content-Range for a partial response"
                        )
                    range_start, range_end, total = (int(value) for value in match.groups())
                    if range_start != existing:
                        raise DownloadError(
                            "server returned a resume range starting at "
                            f"{range_start}, expected {existing}"
                        )
                    if range_end < range_start or range_end >= total:
                        raise DownloadError("server returned an impossible Content-Range")
                    range_length = range_end - range_start + 1
                    if response_length is not None and response_length != range_length:
                        raise DownloadError("Content-Length does not match the returned byte range")
                    resumed = existing > 0
                else:
                    # A server may ignore Range and return 200.  Restart safely instead
                    # of appending a complete response to the partial file.
                    existing = 0
                    total = response_length
                downloaded = existing
                speed_started_at = time.monotonic()
                speed_started_bytes = downloaded
                with partial.open("ab" if resumed else "wb") as stream:
                    while True:
                        control.checkpoint()
                        chunk = response.read(self.chunk_size)
                        if not chunk:
                            break
                        stream.write(chunk)
                        downloaded += len(chunk)
                        progress = min(downloaded / total, 1.0) if total else 0.0
                        if progress_callback:
                            progress_callback(downloaded, total, progress)
                        self._apply_speed_limit(
                            settings.download_speed_limit_kib,
                            downloaded - speed_started_bytes,
                            speed_started_at,
                            control,
                        )
                    stream.flush()
                if total is not None and downloaded != total:
                    raise DownloadError(f"download size mismatch ({downloaded} of {total} bytes)")
            control.checkpoint()
            if target.exists() and settings.overwrite_existing:
                target.unlink()
            partial.replace(target)
            final_size = target.stat().st_size
            if progress_callback:
                progress_callback(final_size, total or final_size, 1.0)
            return DownloadResult(target, final_size, total or final_size)
        except DownloadCancelled:
            if not settings.keep_partial_downloads and partial.exists():
                partial.unlink()
            raise
        except DownloadError:
            if not settings.keep_partial_downloads and partial.exists():
                partial.unlink()
            raise
        except Exception as exc:
            if not settings.keep_partial_downloads and partial.exists():
                partial.unlink()
            raise DownloadError(f"HTTP download failed: {exc}") from exc

    @staticmethod
    def _apply_speed_limit(
        limit_kib: int,
        bytes_transferred: int,
        started_at: float,
        control: DownloadControl,
    ) -> None:
        if limit_kib <= 0:
            return
        expected_elapsed = bytes_transferred / (limit_kib * 1024)
        remaining = expected_elapsed - (time.monotonic() - started_at)
        while remaining > 0:
            control.checkpoint()
            sleep_for = min(remaining, 0.1)
            time.sleep(sleep_for)
            remaining -= sleep_for


class LibtorrentDownloader:
    """Torrent/magnet downloader that imports ``libtorrent`` only on use.

    AniRSS never seeds by default.  When both ``seed_after_completion`` and a
    positive ``seed_time_minutes`` are configured, this adapter seeds only for
    that bounded duration and then pauses/removes the handle without deleting
    downloaded files.
    """

    poll_seconds = 0.5
    max_session_state_bytes = 4 * 1024 * 1024

    def __init__(self, state_path: str | Path | None = None) -> None:
        self._state_path = Path(state_path).expanduser().resolve() if state_path else None
        self._session_lock = threading.RLock()
        self._session: Any | None = None
        self._libtorrent: Any | None = None

    @staticmethod
    def _load_libtorrent():
        try:
            return importlib.import_module("libtorrent")
        except (ImportError, OSError) as exc:
            raise LibtorrentUnavailableError(
                "Torrent support requires the optional 'libtorrent' Python "
                "package. Install a build compatible with this Python version, "
                "or use direct HTTP enclosure links."
            ) from exc

    def _session_for(self, settings: AppSettings) -> tuple[Any, Any]:
        with self._session_lock:
            lt = self._libtorrent or self._load_libtorrent()
            session = self._session
            if session is None:
                session = self._restore_session(lt)
                self._session = session
                self._libtorrent = lt
                self._add_bootstrap_routers(session)
            self._configure_session(session, settings)
            return lt, session

    def _restore_session(self, lt: Any) -> Any:
        state_path = self._state_path
        if state_path is not None and state_path.is_file():
            try:
                if state_path.stat().st_size > self.max_session_state_bytes:
                    raise ValueError("saved libtorrent state is unexpectedly large")
                raw = state_path.read_bytes()
                if raw:
                    read_params = lt.read_session_params
                    return lt.session(read_params(raw))
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                # A corrupt or version-incompatible DHT cache must never make
                # the downloader unusable; start a clean session instead.
                pass
        return lt.session()

    @staticmethod
    def _add_bootstrap_routers(session: Any) -> None:
        add_router = getattr(session, "add_dht_router", None)
        if not callable(add_router):
            return
        for host, port in (
            ("router.bittorrent.com", 6881),
            ("router.utorrent.com", 6881),
            ("dht.transmissionbt.com", 6881),
        ):
            with suppress(Exception):
                add_router(host, port)

    def close(self) -> None:
        """Persist DHT/session state and release the shared engine."""

        with self._session_lock:
            session = self._session
            lt = self._libtorrent
            self._session = None
            self._libtorrent = None
        if session is None:
            return
        with suppress(Exception):
            session.pause()
        state_path = self._state_path
        if state_path is None or lt is None:
            return
        try:
            state = session.save_state()
            raw = bytes(lt.bencode(state))
            if not raw or len(raw) > self.max_session_state_bytes:
                return
            state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = state_path.with_name(state_path.name + ".tmp")
            temporary.write_bytes(raw)
            temporary.replace(state_path)
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            with suppress(OSError):
                temporary = state_path.with_name(state_path.name + ".tmp")
                temporary.unlink(missing_ok=True)

    def download(
        self,
        task: DownloadTask,
        settings: AppSettings,
        control: DownloadControl,
        progress_callback: ProgressCallback | None = None,
    ) -> DownloadResult:
        lt, session = self._session_for(settings)
        directory = Path(task.destination_directory).expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        parameters: dict[str, object] = {"save_path": str(directory)}
        try:
            if task.source_url.lower().startswith("magnet:?"):
                magnet_parameters = lt.parse_magnet_uri(task.source_url)
                if isinstance(magnet_parameters, dict):
                    parameters.update(magnet_parameters)
                    parameters["save_path"] = str(directory)
                    with self._session_lock:
                        handle = session.add_torrent(parameters)
                elif hasattr(magnet_parameters, "save_path"):
                    # libtorrent 2.x returns an add_torrent_params instance.
                    magnet_parameters.save_path = str(directory)
                    with self._session_lock:
                        handle = session.add_torrent(magnet_parameters)
                else:
                    # Some 1.x bindings expose add_magnet_uri as a helper.
                    with self._session_lock:
                        handle = lt.add_magnet_uri(session, task.source_url, parameters)
            else:
                # libtorrent 2.x removed the old add_torrent_params.url
                # downloader.  Fetch and parse the metadata in-process, then
                # pass a real add_torrent_params/torrent_info to the session.
                metadata = self._fetch_torrent_metadata(task.source_url, settings, control)
                if hasattr(lt, "load_torrent_buffer"):
                    loaded = lt.load_torrent_buffer(metadata)
                    loaded.save_path = str(directory)
                    with self._session_lock:
                        handle = session.add_torrent(loaded)
                else:  # compatibility with older 1.2 Python bindings
                    parameters["ti"] = lt.torrent_info(lt.bdecode(metadata))
                    with self._session_lock:
                        handle = session.add_torrent(parameters)
        except DownloadError:
            raise
        except Exception as exc:
            raise DownloadError(f"could not add torrent: {exc}") from exc

        paused = False
        completed_at: float | None = None
        downloaded = 0
        total: int | None = None
        metadata_started_at = time.monotonic()
        last_activity_at = metadata_started_at
        last_downloaded = 0
        metadata_ready = task.kind == DownloadKind.TORRENT
        try:
            while True:
                if control.cancelled:
                    raise DownloadCancelled("download was cancelled")
                if control.paused:
                    if not paused:
                        handle.pause()
                        paused = True
                    control.checkpoint(self.poll_seconds)
                    continue
                if paused:
                    handle.resume()
                    paused = False
                    metadata_started_at = time.monotonic()
                    last_activity_at = metadata_started_at

                status = handle.status()
                error_code = getattr(status, "errc", None)
                try:
                    if error_code is not None and error_code.value():
                        raise DownloadError(f"torrent failed: {error_code.message()}")
                except AttributeError:
                    pass
                progress = float(getattr(status, "progress", 0.0))
                downloaded = int(
                    getattr(status, "total_wanted_done", 0) or getattr(status, "total_done", 0)
                )
                candidate_total = int(getattr(status, "total_wanted", 0) or 0)
                total = candidate_total or None
                has_metadata_method = getattr(handle, "has_metadata", None)
                has_metadata = (
                    bool(has_metadata_method())
                    if callable(has_metadata_method)
                    else total is not None
                )
                now = time.monotonic()
                peer_count = int(getattr(status, "num_peers", 0) or 0)
                seed_count = int(getattr(status, "num_seeds", 0) or 0)
                if has_metadata and not metadata_ready:
                    metadata_ready = True
                    last_activity_at = now
                if downloaded > last_downloaded:
                    last_downloaded = downloaded
                    last_activity_at = now
                if progress_callback:
                    progress_callback(downloaded, total, min(max(progress, 0.0), 1.0))

                if (
                    task.kind == DownloadKind.MAGNET
                    and not metadata_ready
                    and now - metadata_started_at >= settings.bt_metadata_timeout_seconds
                ):
                    raise DownloadError(
                        "magnet metadata timed out after "
                        f"{settings.bt_metadata_timeout_seconds}s "
                        f"({peer_count} peers); retry later or check DHT/trackers"
                    )
                if (
                    metadata_ready
                    and progress < 1.0
                    and now - last_activity_at >= settings.bt_stall_timeout_seconds
                ):
                    raise DownloadError(
                        "torrent received no data for "
                        f"{settings.bt_stall_timeout_seconds}s "
                        f"({peer_count} peers, {seed_count} seeds); retry later"
                    )

                is_seeding = bool(getattr(status, "is_seeding", False))
                if is_seeding or progress >= 1.0:
                    if completed_at is None:
                        completed_at = time.monotonic()
                    seed_seconds = (
                        settings.seed_time_minutes * 60 if settings.seed_after_completion else 0
                    )
                    if seed_seconds <= 0 or time.monotonic() - completed_at >= seed_seconds:
                        break
                time.sleep(self.poll_seconds)
        finally:
            try:
                handle.pause()
                with self._session_lock:
                    session.remove_torrent(handle)
            except Exception:
                pass

        if progress_callback:
            progress_callback(downloaded, total or downloaded, 1.0)
        return DownloadResult(directory, downloaded, total or downloaded)

    @staticmethod
    def _fetch_torrent_metadata(
        url: str,
        settings: AppSettings,
        control: DownloadControl,
    ) -> bytes:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            raise DownloadError("torrent metadata URL must use HTTP or HTTPS")
        handlers: list[urllib.request.BaseHandler] = [
            urllib.request.ProxyHandler(
                {"http": settings.proxy_url, "https": settings.proxy_url}
                if settings.proxy_url
                else {}
            )
        ]
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
                "Accept": "application/x-bittorrent, application/octet-stream;q=0.9",
            },
        )
        try:
            control.checkpoint()
            with urllib.request.build_opener(*handlers).open(
                request, timeout=settings.request_timeout_seconds
            ) as response:
                length_header = response.headers.get("Content-Length")
                if length_header and int(length_header) > MAX_TORRENT_METADATA_BYTES:
                    raise DownloadError("torrent metadata exceeds the 20 MiB limit")
                chunks: list[bytes] = []
                received = 0
                while True:
                    control.checkpoint()
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > MAX_TORRENT_METADATA_BYTES:
                        raise DownloadError("torrent metadata exceeds the 20 MiB limit")
                    chunks.append(chunk)
        except (DownloadError, DownloadCancelled):
            raise
        except Exception as exc:
            raise DownloadError(f"could not fetch torrent metadata: {exc}") from exc
        metadata = b"".join(chunks)
        if not metadata:
            raise DownloadError("torrent metadata response was empty")
        return metadata

    @staticmethod
    def _configure_session(session: object, settings: AppSettings) -> None:
        configured_session = cast(_LibtorrentSession, session)
        configuration: dict[str, object] = {
            "download_rate_limit": settings.download_speed_limit_kib * 1024,
            "upload_rate_limit": settings.upload_speed_limit_kib * 1024,
            "enable_dht": True,
            "enable_lsd": True,
            "enable_upnp": True,
            "enable_natpmp": True,
            "enable_incoming_tcp": True,
            "enable_outgoing_tcp": True,
            "enable_incoming_utp": True,
            "enable_outgoing_utp": True,
        }
        listen_port = settings.listen_port if settings.listen_port else 0
        configuration["listen_interfaces"] = f"0.0.0.0:{listen_port},[::]:{listen_port}"
        try:
            configured_session.apply_settings(configuration)
        except (AttributeError, TypeError):
            if settings.listen_port:
                with suppress(AttributeError):
                    configured_session.listen_on(settings.listen_port, settings.listen_port + 10)


class DownloaderRouter:
    def __init__(
        self,
        http: Downloader | None = None,
        torrent: Downloader | None = None,
    ) -> None:
        self.http = http or HttpDownloader()
        self.torrent = torrent or LibtorrentDownloader()

    def for_task(self, task: DownloadTask) -> Downloader:
        if task.kind in {DownloadKind.MAGNET, DownloadKind.TORRENT}:
            return self.torrent
        return self.http

    def close(self) -> None:
        close = getattr(self.torrent, "close", None)
        if callable(close):
            close()


__all__ = [
    "DownloadCancelled",
    "DownloadControl",
    "DownloadError",
    "DownloadResult",
    "Downloader",
    "DownloaderRouter",
    "HttpDownloader",
    "LibtorrentDownloader",
    "LibtorrentUnavailableError",
    "classify_download",
]
