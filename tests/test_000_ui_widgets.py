import os
from unittest.mock import MagicMock, patch

import pytest
import tkinter as tk
from PIL import Image

from bingo_cards.ui.widgets import HoverToolTip, IconToolbarButton, get_windows_work_area


@pytest.fixture
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


def test_get_windows_work_area_on_windows():
    if os.name != "nt":
        pytest.skip("Windows-only API")
    area = get_windows_work_area()
    assert area is not None
    left, top, right, bottom = area
    assert right > left
    assert bottom > top


def test_get_windows_work_area_non_windows(monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    assert get_windows_work_area() is None


def test_get_windows_work_area_failure(monkeypatch):
    if os.name != "nt":
        pytest.skip("Windows-only API")
    monkeypatch.setattr(
        "bingo_cards.ui.widgets.ctypes.windll.user32.SystemParametersInfoW",
        lambda *args, **kwargs: 0,
    )
    assert get_windows_work_area() is None


def test_hover_tooltip_lifecycle(tk_root):
    label = tk.Label(tk_root)
    label.pack()
    HoverToolTip(label, "Help text", delay_ms=1)
    label.event_generate("<Enter>")
    tk_root.update()
    tk_root.after(10)
    tk_root.update()
    label.event_generate("<Leave>")
    tk_root.update()


def test_hover_tooltip_empty_text_skips_show(tk_root):
    label = tk.Label(tk_root)
    HoverToolTip(label, "")
    label.event_generate("<Enter>")
    tk_root.update()


def test_hover_tooltip_show_and_leave(tk_root):
    label = tk.Label(tk_root)
    label.pack()
    tip = HoverToolTip(label, "Tooltip body", delay_ms=1)
    tip._show()
    tk_root.update()
    assert tip._tip_window is not None
    tip._on_leave()
    assert tip._tip_window is None
    tip._cancel_schedule()


def test_icon_toolbar_button_configure_icon_images(tk_root):
    image = Image.new("RGBA", (24, 24), color=(255, 255, 255, 255))
    button = IconToolbarButton(tk_root, pil_image=image, command=lambda: None, size=32)
    button.pack()
    tk_root.update()
    other = Image.new("RGBA", (24, 24), color=(0, 0, 255, 255))
    button.configure(pil_image=other, pil_image_disabled=other)
    button.configure(state="disabled", fg_color="#111111", hover_color="#222222", command=None)
    assert button.cget("state") == "disabled"


def test_icon_toolbar_button_states(tk_root):
    image = Image.new("RGBA", (24, 24), color=(255, 255, 255, 255))
    clicked = []

    button = IconToolbarButton(
        tk_root,
        pil_image=image,
        command=lambda: clicked.append(True),
        size=32,
    )
    button.pack()
    tk_root.update()
    button.configure(state="disabled")
    button._on_click()
    assert not clicked
    button.configure(state="normal")
    button._on_click()
    assert clicked == [True]
    button._on_enter()
    button._on_leave()
    button.configure(pil_image=image)
    assert button.cget("state") == "normal"
