"""Desktop entry point for the bingo card designer."""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from bingo_cards.ui import BingoDesktopApp
except ModuleNotFoundError as error:
    venv_python = _ROOT / ".venv" / "Scripts" / "python.exe"
    hint = (
        f"Missing dependency: {error.name}\n\n"
        "Install dependencies, then run again:\n"
        f"  {venv_python} -m pip install -r requirements.txt\n"
        f"  {venv_python} ui_desktop.py"
    )
    if sys.stdin.isatty():
        print(hint, file=sys.stderr)
    raise SystemExit(1) from error

if __name__ == "__main__":
    app = BingoDesktopApp()
    app.mainloop()
