"""Annotations must wait until the requested frame has actually been painted."""

from types import SimpleNamespace

from labeling_app import LabelingApp


def test_annotation_is_blocked_while_a_different_frame_is_visible():
    app = SimpleNamespace(video=SimpleNamespace(current_frame=7), displayed_frame=6,
                          state_repo=SimpleNamespace(lock_template=lambda: None))
    assert not LabelingApp._lock_before_annotation(app)


def test_annotation_is_allowed_after_the_requested_frame_is_painted():
    app = SimpleNamespace(video=SimpleNamespace(current_frame=7), displayed_frame=7,
                          state_repo=SimpleNamespace(lock_template=lambda: None))
    assert LabelingApp._lock_before_annotation(app)
