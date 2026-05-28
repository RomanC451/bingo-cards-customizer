from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class PlaylistGenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PlaylistGenerationOptions:
    playlist_url: str
    grid_size: int
    number_of_cards: int
    include_artist_name: bool
    free_center_space: bool


@dataclass(frozen=True)
class PlaylistPdfResult:
    pdf_path: Path
    tracks: list[dict]
    include_artist_name: bool


def _safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")
    return cleaned or "spotify_playlist"


API_BASE = "https://musicbingogenerator.com/wp-json/music-bingo/v1"
DEFAULT_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-CH-UA": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
}


def _post_json(url: str, payload: dict, timeout_s: float) -> dict:
    request = Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://musicbingogenerator.com",
            "Referer": "https://musicbingogenerator.com/",
            **DEFAULT_BROWSER_HEADERS,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise PlaylistGenerationError(
            f"Music Bingo API error ({error.code}): {details[:300]}"
        ) from error
    except URLError as error:
        raise PlaylistGenerationError(f"Could not reach Music Bingo API: {error}") from error

    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise PlaylistGenerationError("Music Bingo API returned invalid JSON.") from error


def _download_file(url: str, destination: Path, timeout_s: float):
    request = Request(
        url=url,
        headers={
            "Accept": "application/pdf,*/*",
            "Referer": "https://musicbingogenerator.com/",
            "Origin": "https://musicbingogenerator.com",
            **DEFAULT_BROWSER_HEADERS,
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            data = response.read()
    except Exception as error:
        raise PlaylistGenerationError(f"Could not download generated PDF: {error}") from error
    destination.write_bytes(data)


def generate_playlist_pdf(
    options: PlaylistGenerationOptions,
    output_dir: Path,
    timeout_ms: int = 120_000,
) -> PlaylistPdfResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    for old_pdf in output_dir.glob("*.pdf"):
        try:
            old_pdf.unlink()
        except OSError:
            pass
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_stem = _safe_stem(f"spotify_{options.grid_size}x{options.grid_size}_{timestamp}")
    output_path = output_dir / f"{file_stem}.pdf"
    timeout_s = max(1.0, timeout_ms / 1000.0)

    try:
        playlist_response = _post_json(
            url=f"{API_BASE}/playlist-from-url",
            payload={"playlist_url": options.playlist_url},
            timeout_s=timeout_s,
        )
        playlist = playlist_response.get("playlist") or {}
        tracks = playlist_response.get("tracks") or []
        if not playlist or not tracks:
            raise PlaylistGenerationError("Could not extract playlist/tracks from API response.")

        generation_payload = {
            "card_count": int(options.number_of_cards),
            "free_space": bool(options.free_center_space),
            "grid_size": int(options.grid_size),
            "include_artist": bool(options.include_artist_name),
            "playlist_id": playlist.get("id"),
            "playlist_image": playlist.get("image"),
            "playlist_name": playlist.get("name"),
            "playlist_snapshot_id": playlist.get("snapshot_id"),
            "tracks": tracks,
        }
        generation_response = _post_json(
            url=f"{API_BASE}/generate-pdf",
            payload=generation_payload,
            timeout_s=timeout_s,
        )
        pdf_url = generation_response.get("pdf_url")
        success = bool(generation_response.get("success"))
        if not success or not pdf_url:
            raise PlaylistGenerationError("Music Bingo API did not return a valid pdf_url.")
        _download_file(pdf_url, output_path, timeout_s=timeout_s)
    except PlaylistGenerationError:
        raise
    except Exception as error:
        raise PlaylistGenerationError(
            f"Failed to generate PDF from playlist API: {error}"
        ) from error

    if not output_path.exists():
        raise PlaylistGenerationError("Generated PDF URL returned, but no local file was saved.")
    return PlaylistPdfResult(
        pdf_path=output_path,
        tracks=list(tracks),
        include_artist_name=bool(options.include_artist_name),
    )
