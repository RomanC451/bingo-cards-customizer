"""Sanity check: pytest runs with the correct pathlib flavor on this OS."""

import pathlib
import sys

import pytest


def test_pathlib_factory_is_windows_flavor():
  if sys.platform != "win32":
    pytest.skip("Windows-only check")

  path = pathlib.Path(".")
  assert type(path).__name__ in {"WindowsPath", "Path"}, (
    f"Expected Windows path type, got {type(path)!r}. "
    "VS Code may be using the wrong interpreter or pathlib was corrupted."
  )
  assert pathlib.Path is not pathlib.PosixPath or pathlib.PosixPath is pathlib.WindowsPath
