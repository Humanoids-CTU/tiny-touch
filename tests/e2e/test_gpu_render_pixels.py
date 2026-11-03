"""GPU pixel checks, isolated from the unit tests and TinyTouch application."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


pytestmark = pytest.mark.gui
DEMOS = Path(__file__).resolve().parents[2] / "demos"


@pytest.mark.parametrize("mode", ["tk", "gpu", "fallback"])
def test_rendered_pixels_keep_frame_identity(tmp_path, mode):
    pytest.importorskip("psutil")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(DEMOS) + os.pathsep + environment.get("PYTHONPATH", "")
    environment["GPU_TEST_MODE"] = mode
    environment["GPU_TEST_OUTPUT"] = str(tmp_path)
    code = """
import os
from pathlib import Path
from gpu_render_demo import enable_dpi_awareness, create_renderer
from benchmark_gpu_render import identity_checks
enable_dpi_awareness()
mode = os.environ['GPU_TEST_MODE']
if mode == 'fallback':
    os.environ['SDL_VIDEODRIVER'] = 'dummy'
try:
    renderer = create_renderer('auto' if mode == 'fallback' else mode)
except (ImportError, RuntimeError) as error:
    if mode == 'gpu':
        print(error)
        raise SystemExit(77)
    raise
try:
    if mode == 'fallback':
        assert renderer.name == 'CPU / Pillow + Tk', renderer.name
    observations = identity_checks(renderer, Path(os.environ['GPU_TEST_OUTPUT']))
    assert len(observations) == 8
finally:
    renderer.close()
"""
    process = subprocess.run([sys.executable, "-c", code], env=environment,
                             capture_output=True, text=True, timeout=30)
    if process.returncode == 77:
        pytest.skip("Accelerated renderer unavailable: " + process.stdout.strip())
    assert process.returncode == 0, process.stdout + process.stderr
