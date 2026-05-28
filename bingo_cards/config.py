import sys
from pathlib import Path


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _bundle_root() -> Path:
    """Read-only packaged assets (icons, etc.)."""
    if _is_frozen():
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


def _writable_root() -> Path:
    """User data next to source tree in dev, next to the .exe when frozen."""
    if _is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


BUNDLE_ROOT = _bundle_root()
PROJECT_ROOT = _writable_root()
ICONS_DIR = BUNDLE_ROOT / "icons"
FREE_IMAGE_PATH = ICONS_DIR / "freee.png"
APP_STATE_PATH = PROJECT_ROOT / "ui_desktop_state.json"
SPOTIFY_TEMP_PDF_DIR = PROJECT_ROOT / "tmp" / "spotify_import"
OUTPUT_JSON_PATH = PROJECT_ROOT / "output.json"

SUPPORTED_GRID_SIZES = (3, 4, 5, 6)
FREE_ICON_SIZE_DEFAULT = 0.85
CUSTOMIZE_UNDO_LIMIT = 50
PREVIEW_REFRESH_DEBOUNCE_MS = 60
SAVE_STATE_DEBOUNCE_MS = 500
