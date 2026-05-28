"""Shared desktop-app fixture for GUI tests (one instance per module)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def app():
    from bingo_cards.ui.app import BingoDesktopApp

    state_dir = Path(tempfile.mkdtemp(prefix="bingo_cards_gui_"))
    state_path = state_dir / "ui_desktop_state.json"
    import bingo_cards.config as config
    import bingo_cards.ui.app as app_module

    config.APP_STATE_PATH = state_path
    app_module.APP_STATE_PATH = state_path

    BingoDesktopApp.after = lambda self, *_a, **_k: "after-id"  # type: ignore[method-assign]
    BingoDesktopApp.after_cancel = lambda self, _id: None  # type: ignore[method-assign]
    BingoDesktopApp.state = lambda self, *a, **k: None  # type: ignore[method-assign]

    instance = BingoDesktopApp()
    instance.update_idletasks()
    yield instance
    try:
        instance.destroy()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _reset_app_state(app):
    app.pdf_path = None
    app.pdf_layout = None
    app.template_path = None
    app.template_image = None
    app.output_dir = None
    app.playlist_tracks = []
    app.music_name_overrides = {}
    app.cached_pdf_cards = None
    app._customize_undo_stack.clear()
    app._customize_redo_stack.clear()
    app._invalidate_preview_caches()
    app._invalidate_free_image_cache()
    yield
