"""Shared fixtures for bingo-cards unit tests."""

from __future__ import annotations

# Fix pathlib before any other imports (VS Code pytest adapter on Windows).
# Same idea as https://discuss.streamlit.io/t/notimplementederror-cannot-instantiate-windowspath-on-your-system/62111
# but reversed: on Windows, PosixPath must not be the active Path flavor.
import sys

if sys.platform == "win32":
    import pathlib

    pathlib.PosixPath = pathlib.WindowsPath
    if pathlib.Path.__name__ == "PosixPath":
        pathlib.Path = pathlib.WindowsPath

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_PDF = PROJECT_ROOT / "tmp" / "spotify_import" / "spotify_5x5_20260528_190338.pdf"
SAMPLE_TEMPLATE = PROJECT_ROOT / "templates" / "Carton-v1-5x5.png"
FREE_ICON = PROJECT_ROOT / "icons" / "freee.png"


def pytest_sessionstart(session) -> None:
    os.chdir(PROJECT_ROOT)


def pytest_sessionfinish(session, exitstatus) -> None:
    os.chdir(PROJECT_ROOT)


def pytest_collection_modifyitems(config, items) -> None:
    """Run GUI tests last so a Tk crash does not look like random unit-test failures."""
    non_gui = [item for item in items if "gui" not in item.keywords]
    gui = [item for item in items if "gui" in item.keywords]
    items[:] = non_gui + gui


@pytest.fixture
def sample_pdf() -> Path:
    if not SAMPLE_PDF.exists():
        pytest.skip(f"Sample PDF not found: {SAMPLE_PDF}")
    return SAMPLE_PDF


@pytest.fixture
def sample_template() -> Path:
    if not SAMPLE_TEMPLATE.exists():
        pytest.skip(f"Sample template not found: {SAMPLE_TEMPLATE}")
    return SAMPLE_TEMPLATE


@pytest.fixture
def tiny_rgb_image() -> Image.Image:
    return Image.new("RGB", (400, 600), color=(240, 240, 240))


@pytest.fixture
def tiny_rgba_icon(tmp_path: Path) -> Path:
    path = tmp_path / "free.png"
    Image.new("RGBA", (64, 64), color=(255, 0, 0, 128)).save(path)
    return path


def make_pdf_page(
    *,
    text: str = "",
    layout_text: str | None = None,
    words: list[dict] | None = None,
) -> MagicMock:
    page = MagicMock()
    layout = layout_text if layout_text is not None else text

    def extract_text(*, layout: bool = False) -> str:
        return layout_text if layout else text

    page.extract_text.side_effect = extract_text
    page.extract_words.return_value = words or []
    return page
