"""Re-apply Windows pathlib fix before VS Code's pytest sessionfinish hook."""

from __future__ import annotations

import sys

import pytest


def _repair_pathlib() -> None:
    if sys.platform != "win32":
        return

    import pathlib
    from pathlib import PosixPath, WindowsPath

    pathlib.PosixPath = WindowsPath
    if pathlib.Path is PosixPath or pathlib.Path.__name__ == "PosixPath":
        pathlib.Path = WindowsPath


def pytest_configure(config) -> None:
    _repair_pathlib()


def pytest_sessionstart(session) -> None:
    _repair_pathlib()


@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session, exitstatus) -> None:
    _repair_pathlib()
