import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

from bingo_cards.playlist.pdf_generator import (
    PlaylistGenerationError,
    PlaylistGenerationOptions,
    _post_json,
    _safe_stem,
    generate_playlist_pdf,
)


def test_safe_stem():
    assert _safe_stem("Hello World!") == "Hello_World"
    assert _safe_stem("***") == "spotify_playlist"


def test_post_json_success():
    payload = MagicMock()
    payload.read.return_value = json.dumps({"ok": True}).encode()
    response = MagicMock()
    response.__enter__.return_value = payload
    response.__exit__.return_value = False

    with patch("bingo_cards.playlist.pdf_generator.urlopen", return_value=response):
        assert _post_json("http://example.com", {"a": 1}, 5.0) == {"ok": True}


def test_post_json_http_error():
    error = HTTPError("http://x", 500, "fail", {}, None)
    error.read = MagicMock(return_value=b"server error")
    with patch("bingo_cards.playlist.pdf_generator.urlopen", side_effect=error):
        with pytest.raises(PlaylistGenerationError, match="500"):
            _post_json("http://example.com", {}, 1.0)


def test_post_json_url_error():
    with patch(
        "bingo_cards.playlist.pdf_generator.urlopen",
        side_effect=URLError("offline"),
    ):
        with pytest.raises(PlaylistGenerationError, match="Could not reach"):
            _post_json("http://example.com", {}, 1.0)


def test_post_json_invalid_json():
    payload = MagicMock()
    payload.read.return_value = b"not-json"
    response = MagicMock()
    response.__enter__.return_value = payload

    with patch("bingo_cards.playlist.pdf_generator.urlopen", return_value=response):
        with pytest.raises(PlaylistGenerationError, match="invalid JSON"):
            _post_json("http://example.com", {}, 1.0)


def test_generate_playlist_pdf_success(tmp_path: Path):
    options = PlaylistGenerationOptions(
        playlist_url="https://open.spotify.com/playlist/abc",
        grid_size=5,
        number_of_cards=2,
        include_artist_name=True,
        free_center_space=True,
    )
    playlist_response = {
        "playlist": {"id": "p1", "name": "Test", "image": "", "snapshot_id": "s1"},
        "tracks": [{"id": "t1", "name": "Song", "artist": "Artist"}],
    }
    generation_response = {"success": True, "pdf_url": "https://example.com/out.pdf"}

    def post_side_effect(url, payload, timeout_s):
        if url.endswith("playlist-from-url"):
            return playlist_response
        return generation_response

    def write_pdf(url, destination, timeout_s):
        destination.write_bytes(b"%PDF-1.4")

    with patch(
        "bingo_cards.playlist.pdf_generator._post_json",
        side_effect=post_side_effect,
    ):
        with patch(
            "bingo_cards.playlist.pdf_generator._download_file",
            side_effect=write_pdf,
        ):
            result = generate_playlist_pdf(options, tmp_path, timeout_ms=5000)
            assert result.pdf_path.exists()
            assert result.include_artist_name is True
            assert len(result.tracks) == 1


def test_generate_playlist_pdf_missing_playlist(tmp_path: Path):
    options = PlaylistGenerationOptions(
        playlist_url="https://open.spotify.com/playlist/abc",
        grid_size=5,
        number_of_cards=1,
        include_artist_name=False,
        free_center_space=False,
    )
    with patch(
        "bingo_cards.playlist.pdf_generator._post_json",
        return_value={"playlist": {}, "tracks": []},
    ):
        with pytest.raises(PlaylistGenerationError, match="extract playlist"):
            generate_playlist_pdf(options, tmp_path)


def test_generate_playlist_pdf_missing_pdf_url(tmp_path: Path):
    options = PlaylistGenerationOptions(
        playlist_url="https://open.spotify.com/playlist/abc",
        grid_size=5,
        number_of_cards=1,
        include_artist_name=False,
        free_center_space=False,
    )
    first = {
        "playlist": {"id": "p1"},
        "tracks": [{"id": "t1", "name": "A", "artist": ""}],
    }

    with patch(
        "bingo_cards.playlist.pdf_generator._post_json",
        side_effect=[first, {"success": False}],
    ):
        with pytest.raises(PlaylistGenerationError, match="pdf_url"):
            generate_playlist_pdf(options, tmp_path)


def test_download_file_writes_bytes(tmp_path: Path):
    from bingo_cards.playlist.pdf_generator import _download_file

    payload = MagicMock()
    payload.read.return_value = b"pdf-bytes"
    response = MagicMock()
    response.__enter__.return_value = payload

    destination = tmp_path / "out.pdf"
    with patch("bingo_cards.playlist.pdf_generator.urlopen", return_value=response):
        _download_file("https://example.com/file.pdf", destination, 5.0)
    assert destination.read_bytes() == b"pdf-bytes"


def test_download_file_failure():
    from bingo_cards.playlist.pdf_generator import _download_file

    with patch(
        "bingo_cards.playlist.pdf_generator.urlopen",
        side_effect=OSError("network"),
    ):
        with pytest.raises(PlaylistGenerationError, match="Could not download"):
            _download_file("https://example.com/x.pdf", Path("nope.pdf"), 1.0)


def test_generate_playlist_pdf_wraps_unexpected_errors(tmp_path: Path):
    options = PlaylistGenerationOptions(
        playlist_url="https://open.spotify.com/playlist/abc",
        grid_size=5,
        number_of_cards=1,
        include_artist_name=False,
        free_center_space=False,
    )
    with patch(
        "bingo_cards.playlist.pdf_generator._post_json",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(PlaylistGenerationError, match="Failed to generate"):
            generate_playlist_pdf(options, tmp_path)


def test_generate_playlist_pdf_missing_file_after_download(tmp_path: Path):
    options = PlaylistGenerationOptions(
        playlist_url="https://open.spotify.com/playlist/abc",
        grid_size=5,
        number_of_cards=1,
        include_artist_name=False,
        free_center_space=False,
    )
    responses = [
        {"playlist": {"id": "p"}, "tracks": [{"id": "t", "name": "A", "artist": ""}]},
        {"success": True, "pdf_url": "https://example.com/x.pdf"},
    ]

    def noop_download(url, destination, timeout_s):
        if destination.exists():
            destination.unlink()

    with patch(
        "bingo_cards.playlist.pdf_generator._post_json",
        side_effect=responses,
    ):
        with patch(
            "bingo_cards.playlist.pdf_generator._download_file",
            side_effect=noop_download,
        ):
            with pytest.raises(PlaylistGenerationError, match="no local file"):
                generate_playlist_pdf(options, tmp_path)


def test_generate_playlist_pdf_cleans_old_pdfs(tmp_path: Path):
    old = tmp_path / "old.pdf"
    old.write_bytes(b"old")
    options = PlaylistGenerationOptions(
        playlist_url="https://open.spotify.com/playlist/abc",
        grid_size=3,
        number_of_cards=1,
        include_artist_name=False,
        free_center_space=False,
    )
    responses = [
        {"playlist": {"id": "p"}, "tracks": [{"id": "t", "name": "A", "artist": ""}]},
        {"success": True, "pdf_url": "https://example.com/x.pdf"},
    ]

    def write_pdf(url, destination, timeout_s):
        destination.write_bytes(b"%PDF")

    with patch(
        "bingo_cards.playlist.pdf_generator._post_json",
        side_effect=responses,
    ):
        with patch(
            "bingo_cards.playlist.pdf_generator._download_file",
            side_effect=write_pdf,
        ):
            generate_playlist_pdf(options, tmp_path)
    assert not old.exists()
