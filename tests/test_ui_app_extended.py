"""Additional BingoDesktopApp coverage for workflows and edge paths."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from bingo_cards.config import APP_STATE_PATH, FREE_IMAGE_PATH

pytest_plugins = ["tests.gui_fixtures"]

@pytest.mark.gui
class TestBingoDesktopAppWorkflows:
    def test_toggle_settings_sections(self, app):
        app._toggle_text_settings()
        assert app.text_settings_expanded
        app._toggle_text_settings()
        assert not app.text_settings_expanded
        app._toggle_grid_settings()
        assert app.grid_settings_expanded

    def test_load_template_success_and_failure(self, app, sample_template, tmp_path):
        assert app._load_template_file(sample_template, show_error=False)
        assert app.template_image is not None
        bad = tmp_path / "not-an-image.txt"
        bad.write_text("nope", encoding="utf-8")
        assert not app._load_template_file(bad, show_error=False)
        assert app.template_image is None

    def test_load_pdf_file(self, app, sample_pdf):
        assert app._load_pdf_file(sample_pdf, show_error=False)
        assert app.pdf_layout == 5

    def test_get_cached_valid_cards(self, app, sample_pdf):
        app._load_pdf_file(sample_pdf, show_error=False)
        cards = app._get_cached_valid_cards()
        assert cards
        cached = app._get_cached_valid_cards()
        assert cached is cards
        reloaded = app._get_cached_valid_cards(force_reload=True)
        assert len(reloaded) == len(cards)

    def test_get_preview_matrix_from_pdf(self, app, sample_template, sample_pdf):
        app._load_template_file(sample_template, show_error=False)
        app._load_pdf_file(sample_pdf, show_error=False)
        matrix = app._get_preview_matrix(5)
        assert len(matrix) == 5

    def test_get_free_image_rgba(self, app):
        image = app._get_free_image_rgba()
        if FREE_IMAGE_PATH.exists():
            assert image is not None
            again = app._get_free_image_rgba()
            assert again is image

    def test_show_preview_warning(self, app):
        app.preview_canvas = MagicMock()
        app.preview_canvas.winfo_width.return_value = 400
        app.preview_canvas.winfo_height.return_value = 300
        app.preview_h_scroll = MagicMock()
        app.preview_v_scroll = MagicMock()
        app._show_preview_warning("Need template")
        app.preview_canvas.create_text.assert_called()

    def test_reset_grid_placement(self, app, sample_template):
        app._load_template_file(sample_template, show_error=False)
        app.pdf_layout = 5
        app.grid_x_var.set(999)
        app._reset_grid_placement()
        assert app.grid_x_var.get() != 999

    def test_on_grid_overlay_toggled(self, app):
        app._customize_history_suppressed = False
        app._on_grid_overlay_toggled()

    def test_pick_text_color_cancelled(self, app):
        with patch("bingo_cards.ui.app.colorchooser.askcolor", return_value=(None, None)):
            app._pick_text_color()

    def test_pick_text_color_applies(self, app):
        app.text_color_var.set("#000000")
        with patch(
            "bingo_cards.ui.app.colorchooser.askcolor",
            return_value=((0, 0, 0), "#ff0000"),
        ):
            app._customize_history_suppressed = False
            app._pick_text_color()
        assert app._normalize_color(app.text_color_var.get()) == "#ff0000"

    def test_refresh_music_name_override_aliases(self, app, sample_pdf):
        app._load_pdf_file(sample_pdf, show_error=False)
        cards = app._get_cached_valid_cards()
        first_cell = cards[0]["songs_matrix"][0][0]
        if first_cell.upper() == "FREE":
            first_cell = cards[0]["songs_matrix"][0][1]
        app.music_name_overrides = {first_cell: "Renamed Track"}
        app._refresh_music_name_override_aliases()
        assert app.music_name_overrides

    def test_music_override_helpers(self, app):
        app.music_name_overrides = {"Song": "Song Prime"}
        assert app._music_override_value_for("Song") == "Song Prime"
        assert app._resolve_music_cell_text("FREE") == "FREE"

    def test_playlist_track_label_list_empty(self, app):
        assert app._playlist_track_label_list() == []

    def test_generate_cards_missing_inputs(self, app):
        with patch("bingo_cards.ui.app.messagebox.showwarning") as warn:
            app._generate_cards()
            assert warn.called

    def test_generate_cards_success(
        self, app, sample_template, sample_pdf, tmp_path
    ):
        app._load_template_file(sample_template, show_error=False)
        app._load_pdf_file(sample_pdf, show_error=False)
        app.output_dir = tmp_path
        with patch("bingo_cards.ui.app.messagebox.showinfo"):
            app._generate_cards()
        outputs = list(tmp_path.glob("card_*.png"))
        assert outputs

    def test_open_output_folder_missing(self, app):
        with patch("bingo_cards.ui.app.messagebox.showwarning") as warn:
            app._open_output_folder()
            warn.assert_called()

    def test_open_output_folder_exists(self, app, tmp_path):
        app.output_dir = tmp_path
        with patch("bingo_cards.ui.app.os.startfile") as startfile:
            app._open_output_folder()
            startfile.assert_called_once_with(tmp_path)

    def test_start_spotify_generation_success_path(self, app, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "bingo_cards.ui.app.SPOTIFY_TEMP_PDF_DIR", tmp_path / "spotify"
        )
        app.spotify_playlist_url_var.set(
            "https://open.spotify.com/playlist/37i9dQZF1DX0XUsuxWHRQd"
        )
        dialog = MagicMock()
        status = MagicMock()
        button = MagicMock()
        with patch("bingo_cards.ui.app.generate_playlist_pdf") as generate:
            from bingo_cards.playlist.pdf_generator import PlaylistPdfResult

            pdf = tmp_path / "gen.pdf"
            pdf.write_bytes(b"%PDF")
            generate.return_value = PlaylistPdfResult(
                pdf_path=pdf, tracks=[], include_artist_name=False
            )
            with patch.object(app, "_on_spotify_pdf_success"):
                app._start_spotify_pdf_generation(dialog, status, button)
        button.configure.assert_called_with(state="disabled")

    def test_tutorial_dialog_helpers(self, app):
        app._open_tutorial_import_dialog()
        assert app._tutorial_import_dialog is not None
        app._close_tutorial_import_dialog()
        app._open_tutorial_music_editor_dialog()
        app._close_tutorial_music_editor_dialog()

    def test_tutorial_ensure_visible_with_real_widget(self, app):
        import tkinter as tk

        app.controls_scrollable = app.controls_scrollable
        target = tk.Label(app, text="target")
        target.place(x=10, y=10)
        app.update_idletasks()
        app._tutorial_ensure_widget_visible(target)

    def test_save_state_handles_write_error(self, app, monkeypatch):
        app._loading_state = False
        mock_state_path = MagicMock()
        mock_state_path.write_text.side_effect = OSError("disk full")
        monkeypatch.setattr("bingo_cards.ui.app.APP_STATE_PATH", mock_state_path)
        app._save_state()
        mock_state_path.write_text.assert_called_once()

    def test_load_state_invalid_json(self, app, monkeypatch, tmp_path):
        APP_STATE_PATH.write_text("{not json", encoding="utf-8")
        app._load_state()

    def test_load_state_restores_spotify_fields(self, app):
        from bingo_cards.config import APP_STATE_PATH

        APP_STATE_PATH.write_text(
            json.dumps(
                {
                    "spotify_playlist_url": "https://open.spotify.com/playlist/test",
                    "spotify_grid_size": "4x4",
                    "spotify_card_count": 15,
                    "spotify_include_artist": True,
                    "spotify_free_center": False,
                }
            ),
            encoding="utf-8",
        )
        app._load_state()
        assert "playlist/test" in app.spotify_playlist_url_var.get()
        assert app.spotify_grid_size_var.get() == "4x4"
        assert app.spotify_card_count_var.get() == 15
        assert app.spotify_include_artist_var.get() is True
        assert app.spotify_free_center_var.get() is False

    def test_preview_zoom_helpers(self, app, sample_template):
        app._load_template_file(sample_template, show_error=False)
        app.preview_base_image = app.template_image
        app.preview_canvas = MagicMock()
        app.preview_canvas.winfo_width.return_value = 800
        app.preview_canvas.winfo_height.return_value = 600
        app.preview_canvas.canvasx.side_effect = lambda x: x
        app.preview_canvas.canvasy.side_effect = lambda y: y
        app.preview_h_scroll = MagicMock()
        app.preview_v_scroll = MagicMock()
        app._set_preview_zoom(1.0, 100, 100)
        app._zoom_in()
        app._zoom_out()
        app._zoom_reset()

    def test_step_float_var(self, app):
        var = pytest.importorskip("tkinter").DoubleVar(value=0.5)
        app._customize_history_suppressed = True
        app._step_float_var(var, 0.1, 0.0, 1.0)
        assert float(var.get()) == pytest.approx(0.6)
