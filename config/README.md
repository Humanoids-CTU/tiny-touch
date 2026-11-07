# Coding configurations

`coding_look.json` is a shareable example. Save named study configurations in
this folder beside the application's `config.json`. Machine preferences remain
in `config.json`; coding files contain only a named, versioned coding setup.

Each configuration includes `schema_version` (currently `1`), `name`,
`template` (`default`, `alternate`, or `general`), `zone_labels`,
`channel_labels`, `parameter_labels`, and `channel_parameter_labels`.
Zone labels are aliases keyed by existing zone IDs; they never change geometry.
Omitted zone aliases display the original zone IDs.

Portable channel names `Channel1`, `Channel2`, `Channel3`, and `Channel4` map to
the stable internal keys `RH`, `LH`, `RL`, and `LL`, respectively. All four
channel labels and all three `Par1`–`Par3` global and channel parameter labels
must be present. Parameter labels describe the existing ON/OFF controls.
New configurations use `P1`–`P3` for global parameters and `CP1`–`CP3` for
channel parameters. Older files using `limb_parameter_labels` remain readable;
saving them uses `channel_parameter_labels` and preserves their explicit labels.
Files containing both keys must give identical labels.

Preparing a video stores an independent copy in its project database and locks
it after successful frame extraction. Editing a file afterwards affects future
videos. Reliability projects inherit the source video's entire coding setup.
Old projects recover labels from their saved zone aliases and export metadata;
missing historical parameter labels require explicit review.
