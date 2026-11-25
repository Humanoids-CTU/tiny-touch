# Coding configurations

Save named study configurations in this folder beside the application's
`config.json`. Machine preferences remain in `config.json`; coding files contain
only a named, versioned coding setup.

Each configuration includes `schema_version` (currently `2`), `name`,
`template` (`default`, `alternate`, or `general`), `zone_labels`,
`zone_layout` (always `numbered`), `channel_zones`, `channel_labels`,
`parameter_labels`, and `channel_parameter_labels`.
Zone labels are aliases keyed by existing zone IDs; they never change geometry.
Omitted zone aliases display the original zone IDs.

Portable channel names `Channel1`, `Channel2`, `Channel3`, and `Channel4` map to
the stable internal keys `RH`, `LH`, `RF`, and `LF`, respectively. All four
channel labels and all three `Par1`–`Par3` global and channel parameter labels
must be present. Parameter labels describe the existing ON/OFF controls.
New configurations use `P1`–`P3` for global parameters and `CP1`–`CP3` for
channel parameters. `channel_zones` lists the zone IDs of each portable
channel; the setup wizard applies the template's fixed assignments. Files made
by an older TinyTouch (schema `1`) cannot be read and must be recreated in the
setup wizard.

Preparing a video stores an independent copy in its project database and locks
it after successful frame extraction. Editing a file afterwards affects future
videos. Reliability projects can import a configuration or use manual setup,
without a local Normal project. A prepared local Normal setup is offered only
as an editable starting point.
