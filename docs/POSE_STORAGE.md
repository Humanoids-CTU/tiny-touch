# Pose working state, version 1

This is internal Pose label storage, separate from the frozen Touch export
contract in `DATA_FORMAT.md`. No Pose export format is defined yet.

`ProjectPaths.pose_state_db` resolves to
`data/<video>/state/<video>_pose.db`, using the existing project/state directories.
The Touch database remains `state/<video>.db`; neither adapter reads the other's
database. Reliability path suffix rules remain those of `ProjectPaths` and do
not establish an implemented Pose Reliability workflow.

## Schema and meaning

| Table | Columns and meaning |
| --- | --- |
| `pose_meta` | `key`, `value`: exactly `kind=tinytouch.pose` and `schema_version=1` |
| `joint_events` | `frame`, `joint`, `event`: primary key `(frame, joint)`, one ON/OFF boundary |
| `frame_quality` | `frame` primary key, `value`: global optional frame quality, inclusive 0..1 |
| `scale_labels` | `frame`, `kind`, `value`, `source`: primary key `(frame, kind)`, body/head factor 0.5..1.5 and manual/carried provenance |

Frames are nonnegative zero-based integers; joint IDs and enum values come from
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
explicitly on load. No migration or historical import is attempted.

All reads/writes/close run on the creating thread. Load uses one read transaction.
Save replaces all three sparse label tables in one transaction; failure rolls
back prior changes. The journal mode is DELETE and synchronous mode FULL, matching
the desktop project's single-writer and synced-folder conventions.

`PoseProjectSession(paths)` opens and loads; `save()` explicitly persists current
labels; `close()` releases storage without an implicit save. Save errors propagate
and retain the session for correction/retry. A new `PoseScaleSession` starts with
both carries inactive on reopen. Saved manual/carried provenance survives exactly;
eligible forward arrival at a manual label can activate carry, and a new manual
edit can overwrite later carried labels while preserving manual barriers.

## Bounded acceptance

`tests/integration/test_pose_persistence.py` covers S7/J5 label roundtrips,
quality 0, explicit neutral, independent deletion, sparse gaps, fresh inactive
carry, continued manual/carried rules, rollback/retry after a mid-save failure,
unsupported-file preservation, corrupt rows, thread confinement and detached
snapshots. These are headless checks, not GUI or packaged-build acceptance.

Notes, global parameters, Special Zones, video/source identity and metadata,
setup/project switching, user-facing save failure handling, exports and GUI
integration remain future work. The database kind identifies only this bounded
Pose label format; it does not establish a complete application project schema.
