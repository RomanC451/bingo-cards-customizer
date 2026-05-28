import importlib.util
from pathlib import Path


def test_ui_desktop_imports_app():
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("ui_desktop", root / "ui_desktop.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    from bingo_cards.ui import BingoDesktopApp

    assert BingoDesktopApp is not None


def test_ui_desktop_main_guard():
    root = Path(__file__).resolve().parent.parent
    content = (root / "ui_desktop.py").read_text(encoding="utf-8")
    assert 'if __name__ == "__main__":' in content
    assert "BingoDesktopApp" in content
