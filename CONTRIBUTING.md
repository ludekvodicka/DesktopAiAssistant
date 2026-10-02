# Contributing

Use a project virtual environment and the dependencies from the README. The desktop app uses PySide6; do not install a second Qt binding.

Run the README's offline checks before submitting a change. Qt tests should use `QT_QPA_PLATFORM=offscreen`.

These suites need a spare interactive Windows desktop and can move focus, send input, or use the clipboard: `test_input_monitor.py`, `test_windows_integration.py`, `test_qt_editor.py`, `test_overlay.py`, and `test_restart.py`. Do not run them while editing an important document. `test_live_provider.py` and `test_frozen_integration.py` contain opt-in live or packaged checks; inspect their environment flags before enabling them.

`test_input_latency.py` is an interactive latency proof enabled only by `DESKTOP_AI_LATENCY_TESTS=1`.
Its legacy positive control delays real mouse input for about 2 seconds. Leave the desktop idle while
running `.venv/Scripts/python.exe -m pytest tests/test_input_latency.py -s -q`; it compares the legacy
hooks with Raw Input under GIL load and prints each delay, the sentinel timing and `LowLevelHooksTimeout`.

`test_background_editor.py` needs the Windows Qt platform plugin. It creates test windows outside
the visible desktop with activation disabled. Capture discovery is supplied by the test so it does
not take focus; content reads, identities and background writes use the real Windows/UIA providers.
The worker fails the test if an insertion attempts to use the clipboard or keyboard input.

Keep credentials, personal settings, history databases, provider jobs, real editor content, build output, and machine-specific paths out of contributions. Use reserved example domains and synthetic test data. Screenshots must come from an isolated demo configuration.

Slow provider calls, UI Automation, and blocking operations belong in workers, not on the Qt event loop. Settings-format changes need versioned migration. Preserve target validation and cancellation.
