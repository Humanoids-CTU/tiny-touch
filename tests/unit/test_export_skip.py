"""`run_export` skips the CSV rewrite only when the CSV cannot be stale.

The caller passes `published_csv`, the stamp `run_export` returned for the CSV
it last published in this session. The CSV is reused only when that stamp
still matches the file on disk AND no frame in the snapshot is dirty;
anything else rewrites it. The metadata is rewritten on every call.

"Rewritten or not" is observed the way a user meets it on Windows: a CSV held
open by another program cannot be replaced, so the export fails exactly when
it tries to rewrite the CSV.
"""
import json
import os

import pytest

from domain.model import empty_bundle
from domain.project import ProjectPaths
from service_layer import save_service
from service_layer.save_service import MetadataInputs, run_export


def _inputs(hours=1.0):
    return MetadataInputs("test", "vid", "Normal", None, None, None, hours * 3600, template="default")


def _frames(changed):
    bundle = empty_bundle()
    bundle["Note"] = "exported"
    bundle["Changed"] = changed
    return {2: bundle}


@pytest.fixture
def paths(tmp_path):
    return ProjectPaths("vid", base_dir=str(tmp_path))


@pytest.fixture
def lock_csv(monkeypatch, paths):
    def lock():
        original = save_service.os.replace

        def replace(source, destination):
            if destination == paths.export_csv:
                raise PermissionError(13, "in use by another program", destination)
            return original(source, destination)

        monkeypatch.setattr(save_service.os, "replace", replace)
    return lock


def _hours(paths):
    with open(paths.export_metadata, encoding="utf-8") as stream:
        return json.load(stream)["Total Labeling Time (hours)"]


def test_unchanged_frames_reuse_the_csv_and_rewrite_the_metadata(paths, lock_csv):
    stamp = run_export(_frames(True), paths, 25, _inputs(1), 9)
    before = open(paths.export_csv, "rb").read()
    lock_csv()

    assert run_export(_frames(False), paths, 25, _inputs(2), 9, published_csv=stamp) == stamp

    assert open(paths.export_csv, "rb").read() == before
    assert _hours(paths) == 2.0


def test_a_dirty_frame_rewrites_the_csv(paths, lock_csv):
    stamp = run_export(_frames(True), paths, 25, _inputs(), 9)
    lock_csv()
    with pytest.raises(PermissionError):
        run_export(_frames(True), paths, 25, _inputs(), 9, published_csv=stamp)


def test_no_published_stamp_rewrites_the_csv(paths, lock_csv):
    run_export(_frames(True), paths, 25, _inputs(), 9)
    lock_csv()
    with pytest.raises(PermissionError):
        run_export(_frames(False), paths, 25, _inputs(), 9, published_csv=None)


def test_a_csv_changed_on_disk_is_rewritten(paths):
    stamp = run_export(_frames(True), paths, 25, _inputs(), 9)
    expected = open(paths.export_csv, "rb").read()
    with open(paths.export_csv, "ab") as stream:
        stream.write(b"edited elsewhere\r\n")
    run_export(_frames(False), paths, 25, _inputs(), 9, published_csv=stamp)
    assert open(paths.export_csv, "rb").read() == expected


def test_a_deleted_csv_is_rewritten(paths):
    stamp = run_export(_frames(True), paths, 25, _inputs(), 9)
    expected = open(paths.export_csv, "rb").read()
    os.remove(paths.export_csv)
    run_export(_frames(False), paths, 25, _inputs(), 9, published_csv=stamp)
    assert open(paths.export_csv, "rb").read() == expected


def test_a_legacy_metadata_sidecar_forces_a_full_rewrite(paths, lock_csv):
    stamp = run_export(_frames(True), paths, 25, _inputs(), 9)
    with open(paths.export_metadata, "w", encoding="utf-8") as stream:
        json.dump({"Export Format Version": 1}, stream)
    lock_csv()
    with pytest.raises(PermissionError):
        run_export(_frames(False), paths, 25, _inputs(), 9, published_csv=stamp)
