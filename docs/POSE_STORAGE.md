# Pose working state, version 3

This is internal Pose label storage, separate from the frozen Touch export
contract in `DATA_FORMAT.md`. Pose setup, controls, timelines and lifecycle are
wired into the application. Every Pose save also publishes the Pose export
(see "Export after each save" below and `POSE_DATA_FORMAT.md`). Pose Analysis is
explicitly deferred.

`ProjectPaths.pose_state_db` resolves to
`data/<video>/state/<video>_pose.db`, using the existing project/state directories.
The Touch database remains `state/<video>.db`; neither adapter reads the other's
database. Normal and Reliability are independent passes using the existing suffix rules.
`ProjectPaths.annotation_type` selects the database: Touch retains `<video>.db`,
Pose uses `<video>_pose.db`. Both may coexist in one video folder and reuse source
frames. Source association is checked against both types before frame reuse.
Unknown sibling source identity is rejected. The library lists each type explicitly.

## Schema and meaning

| Table | Columns and meaning |
| --- | --- |
| `pose_meta` | `key`, `value`: exactly `kind=tinytouch.pose` and `schema_version=3` |
| `project_meta` | `key`, `value`: annotation type, typed coding setup, preparation state, video provenance, timer and resume position |
| `shared_frames` | `frame` primary key, optional `note`, JSON `params` containing only global Par1/Par2/Par3 states |
| `special_zone_points` | `dot_id` primary key, `x`, `y`, `zones`; project-wide Special Zones in the saved dialog's display coordinates |
| `zone_events` | `frame`, `zone`, `event`: primary key `(frame, zone)`, one ON/OFF boundary using an Alternate body/box zone ID |
| `frame_quality` | `frame` primary key, `value`: global optional frame quality, inclusive 0..1 |
| `scale_labels` | `frame`, `kind`, `value`, `source`: primary key `(frame, kind)`, body/head factor 0.5..1.5 and manual/carried provenance |

Frames are nonnegative zero-based integers; Alternate zone IDs and enum values come from
`domain.pose`. Missing rows mean unset. Quality zero and scale neutral 1.0 are
explicit saved values. Deleting one label removes its row without affecting
another label type. Sparse gaps stay unset; storage never fills skipped frames.
Domain validation rejects invalid or duplicate records before publishing labels.

## Save and reopen boundary

`PoseLabels.snapshot()` captures detached immutable data. `PoseLabels.from_snapshot`
rehydrates a validated snapshot through an explicit storage boundary, independent
of interactive setters. It does not imply that a frame was displayed or weaken
the painted-frame checks required for subsequent edits.

`PoseSqliteRepository` preflights existing files read-only, rejecting unknown
kind/version, missing/extra tables, unexpected columns, views and triggers before
changing pragmas. It then opens existing files with SQLite `mode=rw`, so a missing
file is not accidentally recreated during reopen. Invalid saved rows fail
explicitly on load. No migration or historical import is attempted, including from the earlier bounded
Pose v1 label-only and v2 joint-based formats. Existing unsupported files are
preserved and rejected; use a fresh project copy for the Alternate zone workflow.

All reads/writes/close run on the creating thread. Label loading uses one read transaction.
`save_workspace()` writes labels, replaces shared frames and Special Zones and
updates timer, resume position and Special Zones note/scale in one transaction.
Validation happens before writing; failure rolls back the whole workspace and
does not clear dirty flags. Labels past `total_frames` are rejected inside the
transaction by checking the stored result (`MAX(frame)` per label table), so
unchanged labels are covered without scanning them in memory.
Typed setup/source metadata is retained. `save()` is
the explicit labels-only API and preserves shared state. The journal mode is
DELETE and synchronous mode FULL, matching
the desktop project's single-writer and synced-folder conventions.

`PoseProjectSession(paths)` opens and loads; `save()` explicitly persists current
labels; `close()` releases storage without an implicit save. Save errors propagate
and retain the session for correction/retry. A new `PoseScaleSession` starts with
both carries inactive on reopen. Saved manual/carried provenance survives exactly;
eligible forward arrival at a manual label can activate carry, and a new manual
edit can overwrite later carried labels while preserving manual barriers.

### Incremental label saves

Carried scale makes labels dense (two rows per stepped frame), so a save writes
only the label keys changed since the last load or successful save. The stored
rows are identical to a full replace; the schema is unchanged.

- `PoseLabels` records every key its setters touch. `start_tracking()` clears
  that record and issues an opaque token; `pending_changes()` returns a
  validated `PoseChanges` (a `PoseSnapshot` of changed rows plus deleted keys);
  `mark_saved()` forgets what was saved but keeps keys edited again since.
- The repository remembers the token of the labels object it last loaded or
  saved, and SQLite `PRAGMA data_version` at that point. A save is incremental
  only when the labels hold that token and no other connection has committed
  since: deleted keys are `DELETE`d, changed keys `INSERT OR REPLACE`d.
- In every other case (a fresh, rehydrated or foreign `PoseLabels`, labels last
  saved into another store, another writer, or the first save after a failed
  one) the repository replaces all label rows and then adopts the labels as
  its new baseline. When in doubt it replaces; it never skips rows.
- Shared frames and Special Zones are sparse and are still replaced in full.

Measured with body+head carried on 344,033 frames: an unchanged save and a save
after seven edits each take about 5-10 ms (previously 10-14 s). The full-replace
fallback still costs several seconds at that size.

## Export after each save

The database stays the source of truth; the export is derived from it and
never read back. After the workspace transaction commits,
`LabelingApp._publish_pose_export` publishes
`export/<video>_pose_export.csv` and `export/<video>_pose_metadata.json`
(`ProjectPaths.pose_export_csv` / `pose_export_metadata`; format in
`POSE_DATA_FORMAT.md`). The schema and stored rows are unchanged.

- Layers: cell and metadata rules in `domain.pose_export`, file writing in
  `adapters.pose_export_writer`, staging and publishing in
  `service_layer.pose_export_service`.
- Threads: the CSV is written on the save worker thread from
  `PoseLabels.tables()` (shallow copies of the three label tables, about 20 ms
  for 300,000 dense frames; `snapshot()` sorts and validates and takes about
  1.6 s there) and a deep copy of the shared frames. The SQLite connection
  never leaves the Tk thread.
- Outcome: a failed export returns `SaveOutcome.EXPORT_STALE`. The labels are
  committed, the previous export pair is left in place, and the user gets the
  same warning and close / switch-video confirmations as for Touch. A failed
  database save stays `NOT_SAVED` and publishes nothing. Closing with
  "Don't save" publishes nothing.
- CSV skip: the CSV is rewritten unless this session already published it,
  no label, note or parameter changed since (`PoseLabels.has_pending_changes`
  and the shared frames' `Changed` flags, read before the database save clears
  them), and the file still has that export's size and modification time
  (`Video.published_export_csv`). Any export failure drops the stamp. The
  metadata is rewritten on every save.
- A project saved before the export existed has no export files; its next
  save writes them.

Measured with body, head and quality on 300,000 frames (17 MB CSV): a save
that rewrites the CSV spends about 1.2-1.4 s in the export, on the worker
thread; an unchanged save spends about 5 ms (metadata only, on the Tk thread).

## Bounded acceptance

`tests/unit/test_pose_export.py` pins the export columns, cell encodings, a
golden CSV fixture and the metadata keys. `tests/unit/test_pose_export_save.py`
drives the controller's save over a real database and export folder: publishing
from a worker thread, a blocked CSV or metadata file, the unchanged-save skip,
a failed database save, and the close paths including "Don't save".

`tests/integration/test_pose_persistence.py` covers S7/J5 label roundtrips,
quality 0, explicit neutral, independent deletion, sparse gaps, fresh inactive
carry, continued manual/carried rules, rollback/retry after a mid-save failure,
unsupported-file preservation, corrupt rows, thread confinement and detached
snapshots. These are headless checks, not GUI or packaged-build acceptance.
`tests/integration/test_pose_incremental_save.py` counts written rows with
SQLite `total_changes`: unchanged saves write no label rows, edits write only
their rows, deletions leave no stale rows, and failed saves, foreign labels and
other writers fall back to a full replace equal to a fresh full rewrite.
`tests/unit/test_pose_changes.py` covers the pure change tracking.

`tests/integration/test_pose_workspace.py` covers complete transactions, shared
annotation deletion, save retry and the controller Save route including an open
Special Zones dialog. Coordinates are converted through the saved dialog scale
against the neutral Pose masks; they never become frame-level zone ON/OFF events.
`tests/integration/test_pose_load_flow.py` exercises the actual load/publish flow
with real repositories and fake widgets: Pose -> Touch -> Pose, saved labels,
inactive reopened carry, independent Normal/Reliability and cancellation before
any active-project change. Frame extraction, real widgets and workers are outside
that harness. Unit lifecycle tests cover failed close/save retention and rejected
unpainted shared edits. Actual GUI, Linux and packaged builds remain unverified.

## Typed setup foundations (2026-11-13)

`PoseCodingSetup` stores a name, the sole `alternate` template and global parameter
labels. It has no Touch channels or channel parameters. Preparation locks the
accepted setup. The new-video flow chooses Touch/Pose before Normal/Reliability;
Pose preparation offers Alternate and disables Default/General as Coming soon.
Read-only library/setup inspection does not create files. Canceling either dialog
returns before changing the active project. The GUI attaches `PoseProjectSession`
to its existing Pose connection; it does not open a second database.

Pose panel and timeline rendering use separate adapters. Headless setup tests cover typed
reopening, immutable global labels, independent Reliability preparation, sibling
source protection and malformed shared-parameter rejection.

### Pose zone aliases

Pose coding setup includes an optional `zone_labels` mapping from supported
Alternate zone IDs to display names (40 characters maximum). Missing mappings
in existing setups default to no aliases. Labels are immutable after preparation;
annotation IDs and the `zone_events` table are unchanged.
