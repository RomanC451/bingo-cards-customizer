import runpy
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_ui_desktop_missing_dependency_exits_with_code_1():
    root = Path(__file__).resolve().parent.parent
    script = root / "ui_desktop.py"

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "bingo_cards.ui":
            raise ModuleNotFoundError("No module named 'customtkinter'")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        with patch.object(sys, "stdin", MagicMock(isatty=lambda: False)):
            try:
                runpy.run_path(str(script), run_name="__main__")
            except SystemExit as exit_error:
                assert exit_error.code == 1
            else:
                raise AssertionError("Expected SystemExit")
