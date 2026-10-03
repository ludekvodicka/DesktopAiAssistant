# Desktop AI Assistant

**A Windows action ring for editing text, running macros, and keeping useful actions close to the cursor.**

Select text in another app, open the ring, and choose an action. Correct English, switch between formal and casual writing, translate into English, or fix spelling in your native language. The result goes back to the original editor when the target is still safe to edit. Explain reads a selection, a screen region, or the clipboard, then translates or explains it in a reader window.

![Explain menu with translation, explanation and source submenus](docs/images/action-ring.png)

**Windows preview, version 0.6.0.** Built with Python, PySide6 and Qt Quick. Releases provide a per-user Windows installer that keeps the app up to date; build instructions for source runs are below. Editor compatibility varies. Gmail still needs a full signed-in acceptance test.

## What it does

- **Text actions:** **Fix EN → Formal**, **Fix EN → Social**, and **Fix CZ** for your native language, through an installed Claude or Codex CLI. The native language is a setting; Czech is the default. The next ring offers **Current app** (Ctrl+C and Ctrl+V), **UIA plain text** (Windows accessibility with verified insertion), and **Clipboard**.
- **Translate or explain in your native language:** **Explain → Translate to CZ / Explain in CZ**, then a selection, screen region, or clipboard source. Results open in a reader with follow-up questions.
- **A configurable ring:** eight fixed segments, custom labels and icons, and nested submenus. The open ring is controlled by the mouse only; keys keep going to the window underneath, and Esc closes the ring without being taken from that window. A click outside the ring closes it.
- **Macros:** key combinations, text snippets, opening a file or URL, app activation, delays, and AI actions.
- **Application profiles:** keep the main ring stable while changing contextual actions for the focused app.
- **History and restore:** review saved results and restore original text when the target still matches.
- **Chrome and Edge extension:** Gmail compose editing with formatting markers and plain text fields on individually enabled HTTPS sites.

![Action ring editor showing the Explain submenu and its two actions](docs/images/ring-editor.png)

Screenshots use an isolated demo configuration, without personal editor contents, accounts, local paths, or conversation history.

## Text access and editor support

**The browser extension is optional for plain text.** The app can read text through Windows accessibility, talk directly to supported native editors, or use copy and paste. Choose the method to match the editor and whether you need to preserve formatting.

| Method | Where it works | How to use it and what to expect |
|---|---|---|
| **Windows UI Automation (UIA)** | Desktop controls and browser fields that expose accessible text; selected text on web pages | **Translate / Explain → Selection** tries UIA automatically. For editing, choose **Fix → UIA plain text**. It checks the original editor and content before insertion and verifies the result. Replacing text can remove formatting. |
| **Native Windows controls** | Standard Edit controls and supported RichEdit controls | Clicking a Fix action directly selects the Windows adapter. It reads and replaces text through native control messages and verifies the result. Supported controls can receive results in the background. |
| **Notepad++ / Scintilla** | Notepad++ documents | The Windows adapter uses Scintilla's text interface, because Notepad++ does not expose its document through UIA text patterns. It supports selected text or the whole document, verified replacement, and native Undo. |
| **Chrome / Edge extension** | Gmail compose bodies and subjects; plain `input` and `textarea` fields on enabled HTTPS sites | Clicking a Fix action directly in the browser uses the extension. Gmail formatting is preserved, and the original field is checked before insertion. Install the extension and enable each site you want to use. |
| **Copy and paste** | Applications where the selection can be copied and the field accepts pasting | **Fix → Current app** uses Ctrl+C and Ctrl+V with plain text. It cannot verify the pasted result; if focus or input changes, it puts the result on the clipboard for manual insertion. |
| **Clipboard** | Text already copied from any application | **Fix → Clipboard** replaces clipboard text with the result. **Translate / Explain → Clipboard** opens the result in the reader and also accepts formatted text or images. |

For content that cannot be selected, **Translate / Explain → Region** sends a screen region to the AI provider. Translate and Explain display their results in the reader and leave the source application unchanged. If UIA cannot read a selection, they try the browser extension when applicable, then Ctrl+C.

**New in the current source:** browser UIA reading and the explicit **UIA plain text** option shown below. These additions are not included in the published **0.6.0** installer. Chromium text capture has been tested; actual browser insertion, Edge and Firefox still need hands-on verification. UIA support depends on each application's accessibility implementation. Password fields and terminals are refused by the automatic selection reader.

![Fix EN → Formal with Current app, UIA plain text and Clipboard sources; UIA plain text is highlighted](docs/images/uia-plain-text.png)

The additional Fix ring makes the insertion method explicit. Under Translate and Explain, UIA is already part of **Selection**, so no separate UIA choice is needed.

## Download and install

Download `DesktopAiAssistant-Setup-X.Y.Z-x64.exe` from the [latest release](https://github.com/ludekvodicka/DesktopAiAssistant/releases/latest) and check it against `SHA256SUMS.txt` on the same page. Setup installs for the current Windows user, without administrator rights, into `%LOCALAPPDATA%\Programs\DesktopAiAssistant` and adds a Start Menu shortcut. The builds are unsigned, so Windows SmartScreen warns about an unknown publisher: choose **More info**, then **Run anyway**. You still need an installed, signed-in Claude or Codex CLI for AI actions.

- **Updates:** the installed app looks for a new release 45 seconds after start and then every two hours, downloads it in the background and installs it only when it matches the release's `SHA256SUMS.txt`. The tray menu, the Settings sidebar and the **Updates** group on **Overview** show the state. **Restart and install** installs at once; otherwise the update installs on the next quit, never while Windows signs out. Running actions block the install.
- **Portable zip:** `DesktopAiAssistant-X.Y.Z-win-x64.zip` is the update package. Unpacked into a folder you can write to, it runs as it is and updates itself there.
- **Uninstall:** **Settings → Apps → Installed apps → Desktop AI Assistant**. Settings and history in `%LOCALAPPDATA%\DesktopAiAssistant` stay.

If an update is cut off between its two folder renames, rename `DesktopAiAssistant.old` back to `DesktopAiAssistant` in `%LOCALAPPDATA%\Programs` to restore the program.

## Try it from source

You need Windows, Python 3.14, and an installed, signed-in Claude or Codex CLI for AI actions. The project metadata accepts Python 3.12 through 3.14; the supplied lock was generated with Python 3.14 on Windows x64.

```powershell
git clone https://github.com/ludekvodicka/DesktopAiAssistant.git
cd DesktopAiAssistant
py -3.14 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.lock.txt
.venv/Scripts/python.exe -m pip install -e .
.\run.bat
```

Settings opens on startup. Choose your provider under **Languages** and use **Connections** to check the CLI and sign in. Closing Settings leaves the tray app running.

| Control | Default |
|---|---|
| Open or close the ring | `Ctrl+Alt+Space` |
| Stop an action | `Ctrl+Alt+Escape` |
| Reload source changes | **System → Restart app**, or **Restart app** in the tray |
| Exit | **Quit** in the tray |

Both shortcuts are configurable. A mouse button can trigger the ring by mapping it to the same shortcut in your mouse software.

1. Focus a supported editor and select text.
2. Open the ring and choose **Fix EN → Formal**, **Fix EN → Social**, or **Fix CZ**.
3. You can work in another window while the action runs. Supported editors receive the result in the original unchanged field. Other editors wait until you return; **Cancel insertion** stops that pending write.
4. If the result is held back, inspect it in **History**.

With no selection, a text action uses the whole focused field. AI actions never send Enter. Macro key steps can send Enter when explicitly configured.

## A few examples

| Task | Action |
|---|---|
| Polish a work message | Select the draft and choose **Fix EN → Formal**. |
| Write a casual reply | Choose **Fix EN → Social**; lowercase output is configurable. |
| Read a foreign web page | Select a part of the page and choose **Explain → Translate to CZ → Selection**. |
| Understand an unfamiliar term | Choose **Explain → Explain in CZ**, then the source. |
| Insert a prepared sentence | Create a **text** macro with your own snippet. |
| Group writing tools | Add a submenu in **Action ring**, then assign it to a segment. |

These are usage examples, not recorded AI outputs.

![Macro editor showing a harmless Quick reply snippet](docs/images/macros.png)

## Translate and explain

**Explain** contains **Translate to CZ** and **Explain in CZ**, each with three source actions in the next ring. Explanation directly describes meaning, terms and context, including text already in Czech or diagrams in an image. Each source action accepts its own shortcut under **App profiles → Direct action shortcuts**. The language follows the native language set under **Languages**.

| Action | Source |
|---|---|
| **Selection** | The selected text in an editor, web page, or application. Windows UI Automation reads supported controls, including browsers, without the extension or clipboard. With a caret in an editable field, the whole field. Unsupported content falls back to the browser extension, then Ctrl+C with guarded clipboard restoration. Password fields and terminals are refused. |
| **Region** | Drag a rectangle on one screen. Hold Ctrl to move it without resizing; release Ctrl to resize again. Releasing the mouse submits the image for translation or explanation. Esc or a right click cancels. |
| **Clipboard** | Formatted text, plain text, or an image from the clipboard. |

While a translation runs, the status popup shows its progress and **Stop translation**. The reader window then opens, sized to the text, and shows the translation with its structure, **Copy translation**, **Show original**, and **Retry**. Under the translation, **Ask** and **Explain** send questions about the text to the same provider; follow-up questions keep the earlier answers as context. A new translation replaces the content. Translate never writes into the source application. It runs separately from Fix actions, so both can run at the same time; the stop shortcut stops both.

Explanations use the same reader, history and follow-up questions. **Copy explanation** copies the result; **Show original** switches to the captured source. The example below uses synthetic demo text, not a recorded AI response.

![Reader with a Czech explanation of an English idiom, using synthetic demo text](docs/images/explanation.png)

## Browser integration

For browser reading, **Explain → Translate / Explain → Selection** first uses Windows UI Automation. To edit without an extension, select **Fix → UIA plain text**: this reads the selection or whole editable field and verifies the original content and the pasted result. It can remove formatting in the replaced part. UIA insertion waits for the original field to regain focus; support depends on the page's accessibility implementation.

Formatted Gmail editing needs the native host and extension. An installed copy has both in its program folder. For your own build, install Node.js 22 or later, then build the bundle:

```powershell
.\packaging\build.ps1
```

The output is `dist/DesktopAiAssistant`, including the desktop executable, `DesktopAiHost.exe`, and extension. Use the host from your own current build.

1. Start the desktop app. It prepares Native Messaging registration for the current Windows user.
2. Open `chrome://extensions` or `edge://extensions`, enable Developer mode, and load the program's `browser-extension` folder as an unpacked extension: `%LOCALAPPDATA%\Programs\DesktopAiAssistant\browser-extension` for an installed copy, `dist/DesktopAiAssistant/browser-extension` for your own build.
3. On the website you want to edit, open the extension popup and choose **Enable this site**.
4. Confirm both **Access enabled** and **Desktop connected**. Permission and connectivity are separate checks.

Gmail supports compose bodies and subjects; recipient fields are refused. Other enabled HTTPS sites support plain `input` and `textarea` fields. General rich text outside Gmail is not supported.

An app update also replaces the extension files. After updating the extension, reload it and refresh the affected page. The [guide](docs/guide.md) describes formatting, restore, and known limits.

## Privacy and safety

**Selected text is sent to your chosen AI provider.** This is not an offline language model. The app invokes an installed CLI and never silently falls back to an API key. Translate sends the selection, the clipboard content, or the picked screen region to the selected provider only after you choose the action. There is no periodic screen capture. Images are never stored; Codex receives a temporary image file that is deleted after the run.

Local data lives under `%LOCALAPPDATA%/DesktopAiAssistant`. History payloads and bridge credentials use Windows DPAPI for the current user. Settings and macro snippets are ordinary JSON; provider jobs can contain submitted text, and leftover job folders are removed at startup. Review settings exports before sharing them.

The app retains the original editor and selected range, then checks the editor identity and full content before writing. Changed text, a closed editor, or a changed document keeps the result in History. Direct UI Automation replacement works with plain text and may reset the editor's formatting or native Undo; use History to restore the original text. Restore also checks the target and can refuse an unsafe replacement.

**Known limits:** Windows only; compatibility is not universal. Telegram Desktop, Gmail autosave/reopening, and accessibility need further hands-on verification. Elevated windows and general rich text outside Gmail are outside the supported scope. Image translation (screen region and clipboard images) is verified with Claude only. A Ctrl+C read can leave the copied selection in the Windows clipboard history (Win+V).

## Development

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.venv/Scripts/python.exe -m pytest tests/test_core.py tests/test_engine.py tests/test_bridge.py tests/test_browser_setup.py tests/test_ring_editor.py tests/test_settings_layout.py tests/test_clipboard.py tests/test_windows_worker.py tests/test_uia_text.py tests/test_browser_uia.py tests/test_raw_input.py tests/test_translation.py tests/test_region.py tests/test_updates.py tests/test_package_release.py src/desktop_ai_assistant/shared/desktop/autoupdate/tests -q
cd browser-extension
npm ci
npm run build
npm test
```

Additional tests open native windows, manipulate input or the clipboard, launch packaged executables, or call a live provider. Read [CONTRIBUTING.md](CONTRIBUTING.md) before running them.

## License

[MIT](LICENSE). Third-party dependencies retain their own licenses.
