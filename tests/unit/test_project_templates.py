"""Current projects retain their template; unsupported projects stay untouched."""
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from adapters.sqlite_repo import SqliteRepository, SchemaVersionError
from domain.project import ProjectPaths
from domain.templates import TemplateState, DEFAULT_TEMPLATE, ALTERNATE_TEMPLATE
from service_layer.project_service import plan_project_template, apply_project_template


def project(tmp_path, name="baby"):
    return ProjectPaths(name, str(tmp_path))


def create(paths, template=DEFAULT_TEMPLATE):
    repo = SqliteRepository(paths.state_db)
    if template:
        repo.save_template(TemplateState(template))
    repo.close()


def test_empty_project_can_change_but_lock_survives_deletion_and_reopen(tmp_path):
    paths = project(tmp_path)
    repo = SqliteRepository(paths.state_db)
    repo.save_template(TemplateState(DEFAULT_TEMPLATE))
    repo.save_template(TemplateState(ALTERNATE_TEMPLATE))
    repo.save_clothes([(1, 20, 30, "A")], 1.0)
    repo.save_clothes([], 1.0)
    repo.close()
    repo = SqliteRepository(paths.state_db)
    try:
        assert repo.load_template() == TemplateState(ALTERNATE_TEMPLATE, True)
        with pytest.raises(ValueError, match="locked"):
            repo.save_template(TemplateState(DEFAULT_TEMPLATE))
    finally:
        repo.close()


def test_saved_project_overrides_new_project_preference(tmp_path):
    paths = project(tmp_path)
    create(paths)
    plan = plan_project_template(paths, ALTERNATE_TEMPLATE)
    assert plan.template == DEFAULT_TEMPLATE


def test_reliability_inherits_and_locks_both_passes(tmp_path):
    paths = project(tmp_path, "baby_reliability")
    create(paths.original, ALTERNATE_TEMPLATE)
    plan = plan_project_template(paths, DEFAULT_TEMPLATE)
    assert plan.template == ALTERNATE_TEMPLATE
    repo = SqliteRepository(paths.state_db)
    apply_project_template(repo, plan)
    repo.close()
    for candidate in (paths, paths.original):
        assert SqliteRepository.inspect_template(candidate.state_db) == TemplateState(ALTERNATE_TEMPLATE, True)


def test_reliability_without_original_uses_explicit_selection(tmp_path):
    paths = project(tmp_path, "baby_reliability")
    plan = plan_project_template(paths, ALTERNATE_TEMPLATE)
    assert plan.template == ALTERNATE_TEMPLATE
    assert plan.linked_project is None


def test_conflicting_passes_are_rejected_without_changes(tmp_path):
    paths = project(tmp_path, "baby_reliability")
    create(paths)
    create(paths.original, ALTERNATE_TEMPLATE)
    before = {p.state_db: open(p.state_db, "rb").read() for p in (paths, paths.original)}
    with pytest.raises(ValueError, match="different body templates"):
        plan_project_template(paths, DEFAULT_TEMPLATE)
    assert all(open(path, "rb").read() == contents for path, contents in before.items())


def legacy(paths):
    create(paths, template=None)
    with sqlite3.connect(paths.state_db) as conn:
        conn.execute("INSERT INTO frames VALUES (3, 'historical note')")
        conn.execute("PRAGMA user_version=1")


@pytest.mark.parametrize("schema", [0, 1, 999])
def test_unsupported_schema_is_rejected_without_rewriting_or_backing_up(tmp_path, schema):
    paths = project(tmp_path)
    legacy(paths)
    with sqlite3.connect(paths.state_db) as connection:
        connection.execute(f"PRAGMA user_version={schema}")
    before = Path(paths.state_db).read_bytes()
    with pytest.raises(SchemaVersionError):
        repo = SqliteRepository(paths.state_db)
        repo.close()
    assert Path(paths.state_db).read_bytes() == before
    assert not list(tmp_path.rglob("*.bak"))


def test_project_without_recorded_template_is_rejected(tmp_path):
    paths = project(tmp_path)
    create(paths, template=None)
    before = Path(paths.state_db).read_bytes()
    with pytest.raises(ValueError, match="template"):
        plan_project_template(paths, DEFAULT_TEMPLATE)
    assert Path(paths.state_db).read_bytes() == before


def test_export_without_working_database_is_not_opened_as_an_empty_project(tmp_path):
    paths = project(tmp_path)
    Path(paths.export_dir).mkdir(parents=True)
    Path(paths.export_csv).write_text("archived annotations", encoding="utf-8")
    with pytest.raises(ValueError, match="working database"):
        plan_project_template(paths, DEFAULT_TEMPLATE)
    assert not Path(paths.state_db).exists()
    assert Path(paths.export_csv).read_text() == "archived annotations"


def test_unknown_identifier_fails_before_assignment(tmp_path):
    paths = project(tmp_path)
    create(paths)
    with sqlite3.connect(paths.state_db) as conn:
        conn.execute("UPDATE meta SET value='future-v9' WHERE key='template'")
    with pytest.raises(ValueError, match="Unknown body template"):
        plan_project_template(paths, DEFAULT_TEMPLATE)


def test_failed_durable_lock_does_not_mutate_annotation(monkeypatch):
    import labeling_app
    from labeling_app import LabelingApp
    errors = []
    def fail():
        raise sqlite3.OperationalError("disk full")
    app = SimpleNamespace(video=SimpleNamespace(current_frame=0, frames={}),
                          state_repo=SimpleNamespace(lock_template=fail))
    monkeypatch.setattr(labeling_app.messagebox, "showerror", lambda *args, **kwargs: errors.append(args))
    LabelingApp.parameter_dic_insert(app, 1)
    assert app.video.frames == {}
    assert errors
