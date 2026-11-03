"""Check only the isolated refresh experiment's actual Tk widget behavior."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


pytestmark = pytest.mark.gui


def test_changed_only_refresh_matches_current_visible_values():
    demos = Path(__file__).resolve().parents[2] / "demos"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(demos) + os.pathsep + environment.get("PYTHONPATH", "")
    code = """
import tkinter as tk
from benchmark_gui_refresh import validate
root = tk.Tk()
root.withdraw()
try:
    print(f'{validate(root)} widget-state comparisons passed')
finally:
    root.destroy()
"""
    process = subprocess.run([sys.executable, "-c", code], env=environment,
                             capture_output=True, text=True, timeout=30)
    assert process.returncode == 0, process.stdout + process.stderr
