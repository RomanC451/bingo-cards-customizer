"""Tests for BingoDesktopApp logic (CustomTkinter)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import tkinter as tk

from bingo_cards.config import FREE_ICON_SIZE_DEFAULT
from bingo_cards.ui.app import BingoDesktopApp

pytest_plugins = ["tests.gui_fixtures"]


@pytest.mark.gui
class TestBingoDesktopAppHelpers:
    def test_normalize_color(self, app):
        assert app._normalize_color("") == "#000000"
        assert app._normalize_color("ff00ff") == "#ff00ff"
        assert app._normalize_color("#GGGGGG") == "#000000"
        assert app._normalize_color("#AABBCC") == "#aabbcc"

    def test_spotify_url_validation(self, app):
        valid = "https://open.spotify.com/playlist/37i9dQZF1DX"
        assert app._is_valid_spotify_playlist_url(valid)
        assert not app._is_valid_spotify_playlist_url("https://example.com/foo")
        assert not app._is_valid_spotify_playlist_url("ftp://open.spotify.com/playlist/x")
        assert not app._is_valid_spotify_playlist_url("not a url")

    def test_format_output_button_text(self, app):
        assert app._format_output_button_text() == "Browse Output Folder"
        app.output_dir = Path("C:/short")
        assert "Output:" in app._format_output_button_text()
        app.output_dir = Path("C:/" + "x" * 80)
        text = app._format_output_button_text()
        assert text.startswith("Output: ...")

    def test_format_free_icon_label(self, app, tmp_path):
        custom = tmp_path / "my_free_icon.png"
        custom.write_bytes(b"x")
        app.free_icon_path = custom
        label = app._format_free_icon_label()
        assert "FREE Icon:" in label
        assert "my_free" in label

    def test_effective_grid_size(self, app):
        app.pdf_layout = 4
        assert app._effective_grid_size() == 4
        app.pdf_layout = None
        assert app._effective_grid_size() == 5

    def test_step_int_var(self, app):
        var = tk.IntVar(value=5)
        app._customize_history_suppressed = True
        app._step_int_var(var, 3, 1, 10)
        assert var.get() == 8
        app._step_int_var(var, 100, 1, 10)
        assert var.get() == 10

    def test_capture_and_apply_customize_snapshot(self, app, tmp_path):
        icon = tmp_path / "icon.png"
        icon.write_bytes(b"png")
        app.free_icon_path = icon
        snap = app._capture_customize_snapshot()
        app.text_color_var.set("#ffffff")
        app._apply_customize_snapshot(snap)
        assert app._normalize_color(app.text_color_var.get()) == snap["text_color"]

    def test_apply_legacy_offsets(self, app, sample_template):
        app._load_template_file(sample_template, show_error=False)
        app.pdf_layout = 5
        app._apply_legacy_grid_offsets(5, -3)
        assert app.grid_x_var.get() != 0 or app.grid_y_var.get() != 0

    def test_undo_redo_customize(self, app):
        app._customize_history_suppressed = False
        app._loading_state = False
        app.text_color_var.set("#000000")
        app._stash_customize_undo("color")
        app.text_color_var.set("#111111")
        app._undo_customize()
        assert app._normalize_color(app.text_color_var.get()) == "#000000"
        app._redo_customize()
        assert app._normalize_color(app.text_color_var.get()) == "#111111"

    def test_serialize_and_load_state(
        self, app, tmp_path, sample_template, sample_pdf
    ):
        import bingo_cards.config as config

        APP_STATE_PATH = config.APP_STATE_PATH
        APP_STATE_PATH.write_text("{}", encoding="utf-8")

        app._loading_state = False
        app.template_path = sample_template
        app.pdf_path = sample_pdf
        app.output_dir = tmp_path
        app.music_name_overrides = {"A": "B"}
        app.playlist_tracks = [{"id": "1", "name": "Song", "artist": "Art"}]
        payload = app._serialize_state()
        payload["pdf_path"] = None
        assert payload["template_path"] == str(sample_template)
        APP_STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        app.text_color_var.set("#ffffff")
        app._load_state()
        assert app.output_dir == tmp_path
        assert app.music_name_overrides.get("A") == "B"

    def test_preview_layout_and_zoom(self, app, sample_template):
        app._load_template_file(sample_template, show_error=False)
        app.preview_base_image = app.template_image
        layout = app._preview_layout(200, 300)
        assert layout["scroll_w"] >= layout["canvas_w"]
        fit = app._calculate_fit_zoom()
        assert 0.25 <= fit <= 4.0
        app._set_preview_zoom(1.5)
        assert app.preview_zoom == 1.5
        app._set_preview_zoom(10.0)
        assert app.preview_zoom == 4.0

    def test_tutorial_static_overlap(self):
        assert BingoDesktopApp._tutorial_overlaps_target(0, 0, 10, 10, 5, 5, 10, 10)
        assert not BingoDesktopApp._tutorial_overlaps_target(0, 0, 4, 4, 10, 10, 10, 10)

    def test_tutorial_sample_names(self, app):
        assert len(app._tutorial_music_editor_sample_names()) == 3

    def test_music_overrides(self, app):
        app.music_name_overrides = {"Original": "Renamed"}
        matrix = [["Original", "FREE"], ["Other", "Cell"]]
        result = app._apply_music_name_overrides(matrix)
        assert result[0][0] == "Renamed"
        assert result[0][1] == "FREE"

    def test_canonical_cell_text_with_playlist(self, app):
        app.playlist_tracks = [{"id": "1", "name": "Dancing Queen", "artist": "ABBA"}]
        app.playlist_include_artist = True
        matched = app._canonical_cell_text("Dancing Queen")
        assert "Dancing Queen" in matched

    def test_collect_music_names(self, app):
        cards = [
            {
                "songs_matrix": [
                    ["Song A", "FREE"],
                    ["Song A", "Song B"],
                ]
            }
        ]
        names = app._collect_music_names(cards)
        assert names == ["Song A", "Song B"]

    def test_identity_override_map(self, app):
        app.music_name_overrides = {"Song A": "Song A Prime"}
        identity_map = app._identity_override_map(app.music_name_overrides)
        assert identity_map

    def test_expand_music_name_overrides(self, app):
        app.cached_pdf_cards = [
            {"songs_matrix": [["Hello", "World"], ["Hello (feat. X)", "Other"]]}
        ]
        app.music_name_overrides = {"Hello": "Hi"}
        expanded = app._expand_music_name_overrides(app.music_name_overrides)
        assert expanded.get("Hello") == "Hi"

    def test_get_preview_matrix_placeholder(self, app):
        matrix = app._get_preview_matrix(3)
        assert matrix[0][0].startswith("Sample")

    def test_invalidate_caches(self, app):
        app._cached_preview_matrix = [["x"]]
        app._invalidate_preview_caches()
        assert app._cached_preview_matrix is None
        app._invalidate_free_image_cache()
        assert app._cached_free_image is None

    def test_schedule_preview_and_save(self, app):
        app._loading_state = False
        app._schedule_preview_refresh()
        app._schedule_save_state()
        app._flush_preview_refresh()
        app._flush_save_state()

    def test_on_close(self, app):
        with patch.object(app, "destroy"), patch.object(app, "_flush_preview_refresh"), patch.object(
            app, "_flush_save_state"
        ):
            app._on_close()

    def test_spotify_pdf_failure_handler(self, app):
        status = MagicMock()
        button = MagicMock()
        with patch("bingo_cards.ui.app.messagebox.showerror") as show_error:
            from bingo_cards.playlist.pdf_generator import PlaylistGenerationError

            app._on_spotify_pdf_failure(
                status, button, PlaylistGenerationError("api down")
            )
            show_error.assert_called_once()
            button.configure.assert_called_with(state="normal")

    def test_spotify_pdf_success_handler(self, app, tmp_path):
        pdf = tmp_path / "imported.pdf"
        pdf.write_bytes(b"%PDF")
        status = MagicMock()
        button = MagicMock()
        dialog = MagicMock()
        from bingo_cards.playlist.pdf_generator import PlaylistPdfResult

        result = PlaylistPdfResult(
            pdf_path=pdf, tracks=[{"name": "A", "artist": ""}], include_artist_name=False
        )
        with patch.object(app, "_load_pdf_file", return_value=False):
            with patch("bingo_cards.ui.app.messagebox.showinfo"):
                app._on_spotify_pdf_success(dialog, status, button, result)
        status.configure.assert_called()
        dialog.destroy.assert_called_once()

    def test_start_spotify_generation_invalid_url(self, app):
        app.spotify_playlist_url_var.set("bad")
        with patch("bingo_cards.ui.app.messagebox.showwarning") as warn:
            app._start_spotify_pdf_generation(MagicMock(), MagicMock(), MagicMock())
            warn.assert_called_once()

    def test_update_pdf_layout_label(self, app):
        app.pdf_layout = 5
        app._update_pdf_layout_label()
        app.pdf_layout = None
        app._update_pdf_layout_label()

    def test_reset_configs(self, app, sample_template):
        app._load_template_file(sample_template, show_error=False)
        app.text_color_var.set("#ff0000")
        app._reset_configs()
        assert app._normalize_color(app.text_color_var.get()) == "#000000"
        assert app.free_icon_size_var.get() == FREE_ICON_SIZE_DEFAULT
