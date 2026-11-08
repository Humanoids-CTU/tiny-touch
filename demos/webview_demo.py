"""Isolated HTML desktop experiment; no TinyTouch project files are opened."""

import base64
import math
from pathlib import Path
import threading

import cv2
import webview


MAX_PREVIEW_WIDTH = 1280
JPEG_QUALITY = 85
DEFAULT_FPS = 25.0


class VideoApi:
    def __init__(self):
        self._window = None
        self._capture = None
        self._lock = threading.Lock()
        self._index = -1
        self._count = 0

    def open_video(self):
        paths = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            file_types=("Video (*.mp4;*.avi;*.mov;*.mkv;*.m4v)", "All files (*.*)"),
        )
        if not paths:
            return None
        return self._open_path(paths[0])

    def _open_path(self, path):
        with self._lock:
            candidate = cv2.VideoCapture(str(path))
            try:
                count = candidate.get(cv2.CAP_PROP_FRAME_COUNT)
                if not candidate.isOpened() or not math.isfinite(count) or count < 1:
                    raise ValueError("This video could not be opened or has no indexed frames.")
                ok, image = candidate.read()
                if not ok:
                    raise ValueError("The first video frame could not be decoded.")
                result = self._encode(image, 0)
                fps = candidate.get(cv2.CAP_PROP_FPS)
                result.update(name=Path(path).name, count=int(count),
                              fps=fps if math.isfinite(fps) and fps > 0 else DEFAULT_FPS)
            except Exception:
                candidate.release()
                raise
            if self._capture is not None:
                self._capture.release()
            self._capture = candidate
            self._count = int(count)
            self._index = 0
            return result

    def frame(self, index):
        with self._lock:
            if self._capture is None:
                raise ValueError("Open a video first.")
            target = max(0, min(int(index), self._count - 1))
            if target != self._index + 1:
                if not self._capture.set(cv2.CAP_PROP_POS_FRAMES, target):
                    raise ValueError("The decoder could not seek to this frame.")
            ok, image = self._capture.read()
            if not ok:
                self._index = -1
                raise ValueError("This frame could not be decoded.")
            result = self._encode(image, target)
            self._index = target
            return result

    @staticmethod
    def _encode(image, index):
        height, width = image.shape[:2]
        if width > MAX_PREVIEW_WIDTH:
            image = cv2.resize(image, (MAX_PREVIEW_WIDTH, round(height * MAX_PREVIEW_WIDTH / width)))
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            raise ValueError("The preview image could not be encoded.")
        return {"index": index, "image": "data:image/jpeg;base64," + base64.b64encode(encoded).decode("ascii")}

    def _close(self):
        with self._lock:
            if self._capture is not None:
                self._capture.release()
                self._capture = None


def main():
    api = VideoApi()
    api._window = webview.create_window(
        "TinyTouch · Web UI experiment",
        html=Path(__file__).with_name("webview_demo.html").read_text(encoding="utf-8"),
        js_api=api, width=1180, height=820, min_size=(800, 620), background_color="#11151d",
    )
    try:
        webview.start()
    finally:
        api._close()


if __name__ == "__main__":
    main()
