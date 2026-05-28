"""Tutorial flow coverage for BingoDesktopApp."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from bingo_cards.ui.app import BingoDesktopApp

pytest_plugins = ["tests.gui_fixtures"]


@pytest.mark.gui
def test_start_and_close_tutorial(app):
    app._start_tutorial()
    assert app._tutorial_tooltip is not None
    app._tutorial_next()
    app._tutorial_prev()
    app._close_tutorial(mark_seen=True)
    assert app.tutorial_seen
    assert app._tutorial_tooltip is None


@pytest.mark.gui
def test_render_tutorial_step_with_action(app):
    called = []

    app._tutorial_steps = [
        {
            "title": "Step",
            "body": "Body",
            "action": lambda: called.append(True),
            "target": lambda: app.select_template_button,
            "highlight_target": False,
        }
    ]
    app._tutorial_step_index = 0
    app._tutorial_title_label = MagicMock()
    app._tutorial_body_label = MagicMock()
    app._tutorial_progress_label = MagicMock()
    app._tutorial_next_button = MagicMock()
    app._tutorial_back_button = MagicMock()
    app._tutorial_tooltip = MagicMock()
    app._tutorial_tooltip.winfo_exists.return_value = True

    with patch.object(app, "_tutorial_position_tooltip"):
        app._render_tutorial_step()
    assert called == [True]


@pytest.mark.gui
def test_show_tutorial_if_needed_skips_when_seen(app):
    app.tutorial_seen = True
    app._show_tutorial_if_needed()
