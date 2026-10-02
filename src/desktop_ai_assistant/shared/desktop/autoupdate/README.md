# autoupdate

Self-update for a Python desktop app published through GitHub Releases: it checks for a new version after
start and periodically, downloads it in the background, verifies it against the release's SHA256SUMS.txt and
installs it through a helper run of the new build after the app exits. Standard library only, no Qt import:
each app adds a thin layer in its own Qt binding.

Requirements: Python 3.12 or later. The package uses relative imports only, so it works wherever the app
places it inside its own package.

## What the app provides

The member knows no app, repository or path. The app passes:

- the GitHub owner and repository to `UpdateFeedGithub`;
- an `UpdateTarget`: `UpdateTargetFile` (a single program file, replaced in place under its own name) or
  `UpdateTargetFolder` (a program folder, swapped as a whole; the zip's top folder, the program to relaunch
  and a self-contained one-file helper program inside the folder);
- the asset name pattern with a `{version}` field;
- a cache folder for downloads, `pending.json`, `result.json` and `helper.log`;
- an `UpdateHost` that runs timers and background work on its own event loop;
- optional: an SSL context for the transport, a `prepare(staged, installed)` hook for folder targets, and a
  release page function whose result must be an `https` URL on an allowed host.

## Behavior

- First check 45 s after `start()`, then 120 min after each completed check. A failed background check
  keeps the previous state; a failed manual check shows `failed`.
- `UpdateRuntime.resolve` turns build facts into `automatic`, `notify` or `off`: source runs are off,
  frozen Windows and Linux builds with a target and a writable program folder install automatically,
  everything else only shows the release page.
- The asset is downloaded to a `.part` file while hashing and renamed only when its SHA-256 matches the
  line in `SHA256SUMS.txt` of the same release. Zip packages must hold one top folder, no `..`, no
  backslashes, no drive names and no links. A folder target is staged as `<target>.staged` beside the
  program folder.
- States: off, idle, checking, current, available, downloading, ready, installing, failed.
  `UpdateView.describe` gives the text, detail, tone and actions for each.
- `install()` starts the helper and calls the app's quit function; `install_on_quit()` starts it while the
  app quits, with or without a relaunch.
- Release notes are converted from Markdown to plain text, up to the marker `<!-- update-notes-end -->`.

## Helper contract

The helper is the verified new build itself, started as `<program> --apply-update <pending.json>`. The app's
entry point must check `UpdateHelper.requested(sys.argv)` before it imports anything heavy and then exit
with `UpdateHelper.main(sys.argv[1:])`: 0 installed, 1 failed with a result, 2 manifest missing or unreadable.

`pending.json` (schema 1) and `result.json` are the only data that old and new builds share. Every later
build keeps reading schema 1, and readers ignore unknown result fields.

The helper waits for the listed processes to exit, then swaps:

- file target on Windows: copy to `<target>.new`, rename the target to `<target>.old`, rename `.new` to
  the target, roll back on failure;
- file target on Linux: copy to `<target>.new`, mode 0755, atomic replace;
- folder target: rename the target to `<target>.old`, rename `<target>.staged` to the target, roll back
  on failure.

Renames are retried for up to 60 s. The helper writes `result.json` before it relaunches, so the next start
of either build shows a failure. The next start also removes old downloads and `.old`/`.new` leftovers. If a
swap was cut off between the two renames, renaming `<target>.old` back to the target restores the program.

## Proving a build

```
python -m <package>.verify file <built program> [--scratch DIR]
python -m <package>.verify folder <built folder> --executable X --helper Y [--scratch DIR]
```

The tool runs the built program in helper mode against scratch copies and prints `UPDATE HELPER VERIFIED`.

## Modules

| Module | Content |
|---|---|
| `status.py` | release, state and status types |
| `const.py`, `errors.py` | timings, limits, schema numbers; error types |
| `version.py`, `checksums.py`, `release_notes.py` | version compare, SHA256SUMS.txt parsing, notes to text |
| `runtime.py` | targets, runtime facts and the mode decision |
| `view.py` | view model for the update UI |
| `host.py` | the `UpdateHost` protocol |
| `transport.py`, `feed.py` | urllib access with size caps; the latest GitHub release |
| `stager.py` | verified download and staging |
| `manager.py` | the state machine |
| `manifest.py`, `installer.py` | the cross-version files; helper launch and startup outcome |
| `helper.py`, `processes.py`, `files.py` | the swap; process wait and detached start; file helpers |
| `verify.py` | the build check |

Tests are in `tests/` and use pytest; they need no network beyond a loopback server.
