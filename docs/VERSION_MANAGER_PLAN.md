# TinyTouch launcher and version manager plan

Status: agreed product direction; implementation not started.
Recorded: 2026-11-11.

This document preserves the planned change from individually downloaded standalone
executables to a launcher that installs and opens specific TinyTouch releases.
It is an implementation roadmap, not a description of current functionality.
Release numbers, framework selection, and installation paths remain to be decided.

## Purpose and agreed decisions

Labs need to agree on an exact TinyTouch version for a study. A new labeler should
be able to install that version even after newer releases exist. Updates should
be easy to discover without silently changing the research environment.

- Publish one final release using the current standalone EXE distribution first.
  Its version number and release scope are not assigned by this plan.
- Then prepare a new release compatible with the version manager.
- Users open a stable TinyTouch launcher, see a clean loading screen, and can
  select an installed application version and press **Launch TinyTouch**.
- The launcher checks for updates, offers installation, and remembers the selected
  version. Installing a new version does not silently switch that selection.
- Installed versions remain usable offline. An update-service failure must not
  block launching them.
- Older manager-compatible releases can be installed from the release catalog.
- Each exact application version has separate research data, settings, and presets.
  The first implementation makes no cross-version data compatibility guarantee.
- No automatic migration or copying of research data between application versions.
- Removing an application installation preserves its research data.
- Users do not install Python, resolve dependencies, or run package-manager commands.

The manager is more than a conventional auto-updater: several complete application
releases can coexist and remain individually selectable.

## Current implementation and affected areas

The repository currently uses `TinyTouch.spec` to build a single executable with
Python, dependencies, and resources bundled inside it. `.github/workflows/build.yml`
publishes Windows x64 and Linux x64 ZIPs for non-legacy version tags. Application
version metadata is in `src/app_info.py`.

Storage must be addressed before installing applications into version directories:

- `src/gui/resource_utils.py`: `get_app_dir()` uses the executable directory when
  packaged; resource lookup distinguishes bundled files from writable files.
- `src/adapters/config.py`: writes `config.json` beside the executable and currently
  imports path helpers from the GUI package.
- `src/main.py`: initializes logging using the application directory.
- `src/domain/project.py`: `ProjectPaths` defaults to the relative `data/` directory.

Implementation must audit all consumers, including presets, templates, frame
extraction, analysis, exports, logs, and file dialogs. Changing only these four
locations would not prove that every write uses the intended workspace.

Read `ARCHITECTURE.md` before implementing. Preserve the external contract in
`docs/DATA_FORMAT.md`; this work changes storage roots, not project contents or
export schemas. Existing standalone installations must remain untouched.

## Packaging strategy

Recommended starting point: complete PyInstaller **one-directory** application
packages. Each package contains the executable, matching Python runtime, pinned
dependencies, bundled resources, and release metadata.

Do not initially distribute a mutable `src/` folder over a shared Python runtime.
Source changes can require different native libraries or Python versions. Managing
those combinations would add a dependency manager to the launcher and weaken the
guarantee that users run the exact environment tested for a release.

Treat each installed release as immutable: install a new complete package beside
existing versions rather than overwrite a running version's files. A version
identifier must never be republished with different application contents.

Use complete downloads initially. Delta updates (downloading differences between
packages) are an optional later optimization, with a full-package fallback.

### Velopack evaluation

Velopack is an MIT-licensed installer/update framework with Python integration.
Its Python guide uses PyInstaller one-directory output. It is a candidate, not an
approved dependency or proof that our multi-version design is supported.

Evaluate two distinct responsibilities:

1. Installing and updating the stable launcher itself.
2. Installing and retaining independently selectable TinyTouch versions.

A framework designed to update one installed application may not directly provide
our version catalog, retention rules, or workspace isolation. Do not force those
requirements into a single-current-version model. A likely split is a framework
for launcher updates plus a small, explicit application-package manager, but the
packaging prototype must decide this.

Verify current Python APIs, GitHub hosting, signing, portable/installed behavior,
Windows/Linux support, downgrade controls, and recovery behavior. Framework
documentation for another language is not proof of Python API availability.
Velopack's packaging tool requires a .NET SDK on the build machine; this does not
mean users should be asked to install development tools.

## Storage and launch contract

Conceptual layout; platform-specific absolute locations remain an implementation
decision:

```text
Application storage/
    launcher/                    stable entry point, managed separately
    versions/
        <exact-version>/         complete application package
    staging/                     incomplete downloads and extracted candidates
    manager-state.json           installed versions and selected version

User-selected research storage/
    <exact-version>/
        workspace.json           ownership/version marker
        config.json
        presets/                 conceptual; preserve actual preset conventions
        data/                    existing project layout beneath this root
        logs/
```

Install application files into a per-user writable location by default. Research
storage must be visible, selectable, and independent of application cleanup.
Define Windows and Linux locations explicitly; do not hard-code Windows paths.
The launcher needs its own settings/logs outside application-version directories.

Original source videos can stay at their existing shared locations. Do not copy
them for every version. Generated frames and annotation state belong to the
version workspace; initial simplicity may cost additional disk space.

Introduce a non-GUI path component that resolves packaged resources, writable
settings, logs, and the research root. Pass explicit absolute roots to services;
do not rely on the process working directory to isolate data.

Define a small versioned launch contract between manager and application containing
the expected application version, workspace root, and contract revision. Use a
validated configuration/environment mechanism; the project does not authorize a
new command-line interface as part of this plan. The application validates its
workspace marker before writing and refuses a mismatched version.

Specify direct execution behavior as well: launching a managed application's EXE
outside the launcher must either resolve its own correct workspace or show a clear
instruction to use the launcher. It must not silently use relative `data/`.

Default to one running application per workspace, enforced with an OS-backed lock
that releases on process exit. Installing another version while annotation is
running may be allowed, but switching/closing must respect pending saves and exports.

## Launcher experience

### Startup

1. Show a branded splash/loading screen immediately.
2. Load local installation state and the last selected version.
3. Check release metadata in the background with a bounded timeout. Proposed
   starting value: five seconds, adjustable as a named constant.
4. Present the launcher without waiting indefinitely for the network. An installed
   version can be launched while the remote check is pending.
5. Show a quiet offline/check-failed status when appropriate; retain manual retry.

The default destination is the version selector and Launch button, not automatic
launch of a newly downloaded release. A future auto-launch preference is out of
scope. On first installation, bundle a current application package if practical;
otherwise explain that an initial download is required. Offline first use without
any installed package cannot launch TinyTouch and must be handled explicitly.

### Main screen

```text
                         TinyTouch

    Research version
    [ <selected-version> - installed                  v ]

    Workspace: <research-root>/<selected-version>
    Open workspace

                   [ Launch TinyTouch ]

    A newer version is available.              [ Install ]
    Install another version
```

Show the selected exact version prominently. Available versions should distinguish
installed, downloadable, unsupported-platform, and withdrawn releases. Offer release
notes, download size, and manual checks. Include Later/Skip for update notices and
an option to disable automatic checks.

The first version uses stable releases only; preview channels are deferred. A lab
can pin its agreed version by retaining the selected version and dismissing update
offers. Matching versions does not replace matching study presets and procedures.

### Installing and switching versions

1. User chooses the latest available release or an older supported release.
2. Confirm the target version and explain that it has a separate workspace.
3. Download with progress, cancellation, and actionable failure messages.
4. Verify and install the package before showing it as launchable.
5. Refresh the selector and offer **Launch this version**. Preserve the previous
   selection unless the user explicitly chooses the new version.

An application-package installation should not require restarting the launcher.
If the chosen framework requires a restart, return to the same launcher screen and
preserve selection. A launcher self-update may restart the launcher after consent.
Never terminate an active annotation session to apply an update.

## Installation, integrity, and recovery

Use an explicit state progression:

```text
Available -> Downloading -> Verifying -> Staging -> Installed -> Launchable
```

- Download only expected platform/architecture assets from the configured release
  source. Never interpret a release description as executable instructions.
- Check free space for the compressed package and extracted files before installing.
- Download to a temporary file, verify length/hash, and authenticate the package
  using the chosen signed-metadata/package scheme before execution. A checksum
  retrieved from the same server alone does not establish publisher identity.
- Extract into a staging directory. Reject archive paths or links escaping that
  directory; validate the package manifest, entry point, and required resources.
- Publish the complete version directory through a same-volume rename where
  supported. Persist manager state atomically and reconcile it with disk on startup.
- Never overwrite an existing version with different content. Reject a collision.
- Serialize installation/uninstallation with a manager lock. Keep running versions
  intact; handle multiple launcher attempts without racing file operations.
- Cancellation, disk-full conditions, failed verification, or a crash must leave
  already installed versions launchable. Recover or clean incomplete staging on
  next startup; cleanup must never traverse into research storage.
- Retain earlier versions until the user removes them. Removing binaries never
  removes workspaces. Display disk usage so retention is understandable.

A successful process spawn is not proof of a healthy application. Define a bounded
startup-ready signal after essential initialization and usable UI creation. On
failure, preserve diagnostics and offer another installed version. Do not interpret
a normal user exit as a failed update or repeatedly restart a crashing version.

Returning to an earlier application opens that earlier version's workspace. It does
not transfer annotations made in the newer version. The UI must state this clearly;
application recovery is not data rollback.

For Windows distribution, plan publisher signing and executable metadata/icons.
Signing does not guarantee immediate elimination of SmartScreen warnings. Determine
the signing provider and package-verification trust model before public deployment.

## Release catalog and publishing

GitHub Releases remains the initial hosting candidate. Query a catalog of supported
releases rather than only the latest-release endpoint, since older installations
are a core feature. Handle pagination, caching, timeouts, rate limits, deleted assets,
and releases without a matching platform package. Do not embed account credentials.

Define a machine-readable release manifest, with schema revision, containing:

- Exact application version and source revision.
- Platform/architecture and package asset name, byte size, and digest.
- Entry point and launch-contract revision.
- Minimum supported launcher version.
- Workspace ownership/version policy.
- Release notes reference and any withdrawal information.

Finalize whether signed metadata is embedded in each release or also provided by a
separate catalog. Authentication must cover the executable package identity. Release
notes are display content, not a source of installation paths or commands.

Use separate versioning/release identities for launcher and application packages.
The launcher-update check and the application-update check are separate operations.
An app requiring a newer launcher should explain that requirement and offer the
launcher update without blocking older compatible applications.

The build workflow must create complete platform packages, validate manifests,
sign the required artifacts, and publish the catalog entry only once assets are
ready. Keep dependency versions pinned and record build provenance. Retain old
supported packages so new labelers can join studies on the agreed version.

Define a withdrawal policy: stop advertising a defective release for new installs,
explain the reason, and preserve local research workspaces. Do not silently replace
an already installed release. Treat any exceptional security policy separately.

## Transition from standalone releases

1. Finish and publish the final standalone release through the existing workflow.
   This plan does not authorize publishing, tagging, or committing it automatically.
2. Keep its download, documentation, and existing research folders available.
3. Prototype the manager using test packages, without modifying that release.
4. Prepare the first manager-compatible application with explicit paths and a
   launch contract. Assign its version when implementation scope is settled.
5. Publish the launcher distribution and explain the new version/workspace model.
6. Existing users download the launcher manually once. The final standalone EXE
   does not become update-capable retroactively.

Initially, the catalog offers only manager-compatible application releases.
Installing older releases means older releases within this supported family, not
arbitrary historical EXEs. Supporting pre-manager executables needs separate tests
and an explicit compatibility design.

Do not automatically import standalone research data into a new version. Users can
continue existing studies with the final standalone release. Any future migration
must be a separate, deliberate operation on a copy with preserved originals.

## Implementation work packages

### 1. Prove packaging and framework fit

- Build a minimal launcher and two complete test application packages.
- Demonstrate installation, exact-version selection, offline launch, and retained
  versions on a clean Windows test machine without Python.
- Evaluate Velopack separately for launcher updates and application management.
- Establish a Linux packaging/launch path and document platform-specific limitations.
- Decide installed versus portable distribution, signing, and first-install bundle.

Exit condition: documented framework decision backed by working packaged artifacts,
not only source-mode tests or framework examples.

### 2. Separate resources, settings, and workspace paths

- Introduce the explicit path/launch-contract components and audit all consumers.
- Make application defaults read-only resources and user settings writable copies.
- Enforce workspace-version ownership and handle direct EXE execution safely.
- Preserve source development and existing standalone behavior as required during
  transition; validate from a different working directory.

Exit condition: two packaged versions write exclusively to their own workspaces,
with project contents and external export contracts unchanged.

### 3. Implement manager services

- Catalog reader, version comparison, package verification, staging/installation,
  installed-version registry, process launch, and startup health reporting.
- Explicit installation state and recovery after interruption.
- Separate launcher-update integration from application-package installation.
- Keep network/filesystem adapters and orchestration independent of GUI widgets.

Exit condition: headless service tests exercise ordinary operation and failure paths.

### 4. Build the user experience

- Splash, selector, release notes, installation progress/cancellation, launch action,
  workspace access, installed-version removal, and offline/error messages.
- Remember selection; make workspace isolation visible before opening a new version.
- Use background work for network/downloads without blocking the UI.
- Preserve pending annotation saves/exports during any coordinated shutdown.

Exit condition: the complete packaged flow is understandable to a new labeler and
does not interrupt an existing annotation session.

### 5. Release integration and acceptance

- Add manifests, platform packages, signing, and supported-release discovery to CI.
- Document installation, study version pinning, workspace locations, retention,
  recovery, and the absence of automatic cross-version migration.
- Validate the release on isolated Windows and Linux environments.

## Acceptance checks

Use focused automated tests during development. Follow repository major-release
test requirements before publication. GUI tests run only when explicitly needed
and with a suitable isolated display; do not disrupt the active desktop.

Required scenarios include:

- Offline startup, slow network, unavailable GitHub, rate limiting, and first launch
  with no installed application.
- Installing current and older supported releases; selection survives manager restarts.
- Installing a new release does not change a lab's selected version.
- Two versions retain separate config, presets, annotations, exports, and logs.
- Launch from a shortcut or unrelated working directory; direct EXE handling.
- Save/export completion before any requested application shutdown.
- Invalid signature/hash, wrong platform, malformed manifest, unsafe archive paths,
  interrupted download, cancellation, disk full, and crash during publication.
- Startup reconciliation after interruption; existing versions remain usable.
- Failed application startup with useful diagnostics and no restart loop.
- Concurrent manager attempts and attempts to remove a running version.
- Removing/reinstalling application binaries preserves the associated workspace.
- No accidental migration or overwriting of standalone research data.
- Clean machines without Python, Unicode/spaces in paths, and permissions failures.
- Launcher self-update preserves installation registry, chosen version, and data.

## Deferred work and open decisions

Deferred: cross-version import/migration, shared writable data between versions,
source-only updates, runtime dependency installation, preview channels, automatic
launch, arbitrary historical EXEs, and delta-download optimization.

Decide during the prototype: launcher implementation technology, Velopack role,
exact OS storage locations, portable distribution requirements, first-install
bundle, minimum supported OS versions, signing/trust scheme, release-manifest
format, and launcher/application release naming. No application or UI framework
rewrite is implied by this plan.

## Reference material

Official sources reviewed during the planning conversation; recheck their current
APIs and behavior when implementation begins:

- [PyInstaller operating modes](https://pyinstaller.org/en/stable/operating-mode.html)
- [Velopack Python integration](https://docs.velopack.io/getting-started/python)
- [Velopack source and MIT license](https://github.com/velopack/velopack)
- [Velopack delta packages](https://docs.velopack.io/packaging/deltas)
- [GitHub Releases API](https://docs.github.com/en/rest/releases/releases)
- [Windows signing and SmartScreen reputation](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)
