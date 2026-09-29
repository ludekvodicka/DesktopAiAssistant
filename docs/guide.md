# Using Desktop AI Assistant

## Configure the ring

Open **System → Open config**. In **Action ring**, click a segment to select it, then choose **Change action**. The preview never executes an action. Save applies changes to the live ring.

Use **New submenu** to group up to six actions. Submenus may contain other submenus, up to eight levels deep. The app rejects circular references. Hover opens the first submenu; entering a nested group replaces the contents of the outer arc. The center's **Back** action returns to the preceding group.

## Language actions

**Languages** selects the provider, social lowercase output, and rules for each action. **Connections** checks the CLI and provides sign-in controls. Codex uses an app-specific login directory; Claude uses its existing CLI authentication.

![Language settings with the three built-in writing actions](images/languages.png)

**Formal** and **Social** correct English or translate Czech into the corresponding English style. **Čeština** corrects Czech. Custom rules complement the built-in formatting and protected-literal checks.

## Macros and application profiles

| Step | Behavior |
|---|---|
| `keys` | Send the explicitly configured key combination. |
| `text` | Insert a snippet or replace the selection. |
| `open` | Open a file, application, or HTTP(S) URL without evaluating a shell command. |
| `activate` | Focus a window by exact executable name; ambiguous matches are refused. |
| `delay` | Wait for the configured number of seconds. |
| `ai` | Run a language action. |
| `app` | Run an available built-in application command. |

An `open` step does not prove that a window is ready. Add explicit activation before subsequent input. Macros can partially complete before a later step fails. A key step can send Enter if you add it.

Profiles match exact executable filenames. New installations start with no profiles. The optional Jamat integration accepts a CLI wrapper path and project directory in Connections. Its reMarkable command is disabled because that integration is not implemented.

## History and restore

You can switch windows while an AI action runs. Native Windows Edit controls, writable UI Automation
fields, and plain browser fields can receive the result in the original field in the background.
The app compares the entire original content and target identity before writing. A different document,
closed editor, or changed text stops insertion and keeps the result in History.

Editors requiring a keyboard paste and formatted Gmail fields wait for you to return to the same
unchanged field. **Result ready** identifies this state; **Cancel insertion** or the stop shortcut
cancels the pending write while retaining the result. Only one action runs at a time, including this
waiting period. The app never brings the target window to the foreground for automatic insertion.

Direct UI Automation writes replace the field's plain text value. They can reset formatting and
the editor's native Undo. Use these desktop actions on plain text; original text remains available
through History. Text containing `<` waits for foreground insertion because some editors treat it
as HTML. Native Windows Edit and the browser adapter use their own addressed replacement paths.

History contains original text, results, status, and errors. Copying the original is available independently of restore.

Select an applied result and choose **Restore**, focus the original editor, then press the ring shortcut. Restore requires a matching target and refuses when the document has changed. Browser navigation or a restarted app can invalidate the target.

## Gmail and browser fields

The extension keeps Gmail's original DOM structure locally and passes text with immutable formatting markers to the model. Links, attributes, images, signatures, and quoted regions are not accepted as arbitrary model-generated HTML. Invalid markers or altered protected literals cause rejection.

Enable sites individually. Plain text fields work on enabled HTTPS sites; rich text is limited to Gmail compose. When the extension is unavailable, Gmail does not fall back to a plain-text desktop paste.

Switching to another tab or window does not discard a plain-field result. The extension addresses the
saved tab and field, checking its document, URL, identity and full content. Gmail's formatted body
waits until that original field is focused again, then applies the originally captured range.
Navigating, closing, replacing or changing the source field stops insertion. After an update,
reload the unpacked extension and refresh the page.

## Storage and boundaries

The default data folder is `%LOCALAPPDATA%/DesktopAiAssistant`. Development and isolated tests can override it with `DESKTOP_AI_DATA`.

History payloads and bridge credentials use DPAPI for the current Windows user. This does not encrypt every file in the folder. Settings and macro snippets are ordinary JSON. Provider jobs can contain submitted text. Protect this folder as personal data.

History retention is configurable. Settings import is a preview until Save and never runs imported actions. Review exports for private snippets or paths before sharing.

## Verification limits

Native Windows Edit controls have integration coverage for selected text, whole-field replacement, stale content, and input guards. Other desktop editors use UI Automation or a clipboard path and need app-specific verification.

Gmail structure has DOM tests, but signed-in editing, autosave, and reopening a draft still need end-to-end acceptance. Test with a draft without recipients. Telegram Desktop is not claimed as verified. Password fields, elevated targets, general rich text outside Gmail, and non-Windows platforms are outside the supported scope.
