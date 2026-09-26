"""I/O utilities for render service: downloads, uploads, allowlist, progress posting."""

from __future__ import annotations

import ipaddress
import os
import re
import urllib.parse
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from render_service.manifest import InputRef, RenderError

if TYPE_CHECKING:
    pass


class FetchError(Exception):
    """Raised when downloading or uploading an asset fails or URL check fails."""


class TooLargeError(Exception):
    """Raised when download or render exceeds maximum byte limit."""


DEFAULT_ALLOWED_HOSTS = (
    "supabase.co",
    "videos.pexels.com",
    "player.vimeo.com",
    "cdn.pixabay.com",
)

KIND_EXTENSIONS = {
    "video": ".mp4",
    "image": ".png",
    "audio": ".mp3",
    "html": ".html",
}


def allowed_hosts() -> tuple[str, ...]:
    env_val = os.getenv("RENDER_ALLOWED_HOSTS")
    if not env_val or not env_val.strip():
        return DEFAULT_ALLOWED_HOSTS
    hosts = [h.strip() for h in env_val.split(",") if h.strip()]
    return tuple(hosts) if hosts else DEFAULT_ALLOWED_HOSTS


def check_url(url: str) -> None:
    if not isinstance(url, str):
        raise FetchError("URL must be a string")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise FetchError(f"URL scheme must be 'https', got '{parsed.scheme}'")

    netloc = parsed.netloc or ""
    if "@" in netloc or parsed.username or parsed.password:
        raise FetchError("URL contains credentials")

    hostname = parsed.hostname
    if not hostname:
        raise FetchError("URL missing hostname")

    try:
        ipaddress.ip_address(hostname)
        raise FetchError(f"Literal IP addresses not allowed: '{hostname}'")
    except ValueError:
        pass  # Not a literal IP address

    h = hostname.lower()
    allowed = allowed_hosts()
    is_allowed = any(
        h == a.lower() or h.endswith("." + a.lower()) for a in allowed
    )
    if not is_allowed:
        raise FetchError(f"Host '{hostname}' is not in allowed hosts allowlist")


def redact(text: str) -> str:
    cleaned = RenderError.sanitize_detail(text)
    cleaned = re.sub(r"\?[^\s#'\"]*", "", cleaned)
    cleaned = re.sub(r"token=[^\s&'\"]*", "token=REDACTED", cleaned)
    if len(cleaned) > 500:
        cleaned = cleaned[:500]
    return cleaned


def download(
    url: str,
    dest: Path,
    max_bytes: int,
    timeout_s: float = 60.0,
    client: httpx.Client | None = None,
) -> int:
    current_url = url
    redirect_count = 0
    max_redirects = 3

    own_client = False
    if client is None:
        client = httpx.Client(timeout=timeout_s, follow_redirects=False)
        own_client = True

    try:
        while True:
            check_url(current_url)
            req = client.build_request("GET", current_url)
            resp = client.send(req, stream=True)

            if resp.status_code in (301, 302, 303, 307, 308):
                resp.close()
                redirect_count += 1
                if redirect_count > max_redirects:
                    raise FetchError("Too many redirects")
                location = resp.headers.get("location")
                if not location:
                    raise FetchError("Redirect response missing location header")
                current_url = urllib.parse.urljoin(current_url, location)
                continue

            if resp.status_code >= 300:
                resp.close()
                raise FetchError(f"HTTP GET failed with status code {resp.status_code}")

            total_bytes = 0
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                with open(dest, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=16384):
                        if chunk:
                            total_bytes += len(chunk)
                            if total_bytes > max_bytes:
                                raise TooLargeError(
                                    f"Download size ({total_bytes} bytes) exceeded limit of {max_bytes} bytes"
                                )
                            f.write(chunk)
            except Exception:
                if dest.exists():
                    try:
                        dest.unlink()
                    except OSError:
                        pass
                raise
            finally:
                resp.close()

            return total_bytes
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        if dest.exists():
            try:
                dest.unlink()
            except OSError:
                pass
        raise FetchError(f"Download network error: {e}") from e
    finally:
        if own_client:
            client.close()


def download_all(
    inputs: dict[str, InputRef],
    workdir: Path,
    per_input_max: int = 300_000_000,
    total_max: int = 800_000_000,
    client: httpx.Client | None = None,
) -> dict[str, Path]:
    local_map: dict[str, Path] = {}
    cum_bytes = 0
    try:
        for input_id, item in inputs.items():
            ext = KIND_EXTENSIONS.get(item.kind, ".bin")
            filename = f"{uuid.uuid4().hex}{ext}"
            dest_path = workdir / filename
            nbytes = download(
                url=item.url,
                dest=dest_path,
                max_bytes=per_input_max,
                client=client,
            )
            cum_bytes += nbytes
            if cum_bytes > total_max:
                raise TooLargeError(
                    f"Total download size ({cum_bytes} bytes) exceeded total limit of {total_max} bytes"
                )
            local_map[input_id] = dest_path
        return local_map
    except Exception:
        for p in local_map.values():
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass
        raise


def upload(
    upload_url: str,
    path: Path,
    content_type: str = "video/mp4",
    client: httpx.Client | None = None,
) -> None:
    check_url(upload_url)
    if not path.is_file():
        raise FetchError(f"Upload source file does not exist: {path}")

    own_client = False
    if client is None:
        client = httpx.Client(timeout=120.0)
        own_client = True

    try:
        headers = {
            "Content-Type": content_type,
            "x-upsert": "false",
        }
        with open(path, "rb") as f:
            resp = client.put(upload_url, content=f, headers=headers)
        if resp.status_code >= 300:
            raise FetchError(
                f"Upload failed with HTTP status code {resp.status_code}"
            )
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        raise FetchError(f"Upload network error: {e}") from e
    finally:
        if own_client:
            client.close()


def post_progress(
    url: str | None,
    secret: str,
    pct: int,
    client: httpx.Client | None = None,
) -> None:
    if not url:
        return

    allowed_hosts = [
        h.strip().lower()
        for h in os.getenv(
            "RENDER_PROGRESS_HOSTS", "brand-studio-agent.onrender.com"
        ).split(",")
        if h.strip()
    ]
    parsed = urllib.parse.urlparse(url)
    if not parsed.hostname or parsed.hostname.lower() not in allowed_hosts:
        return

    own_client = False
    if client is None:
        client = httpx.Client(timeout=3.0)
        own_client = True
    try:
        headers = {"Authorization": f"Bearer {secret}"}
        client.post(url, json={"pct": pct}, headers=headers)
    except Exception:
        pass
    finally:
        if own_client:
            client.close()

