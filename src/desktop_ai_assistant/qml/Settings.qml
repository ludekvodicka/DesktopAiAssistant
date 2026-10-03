import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Window

ApplicationWindow {
    id: window
    width: 1100; height: 780; minimumWidth: 940; minimumHeight: 660
    visible: false; title: "Desktop AI Assistant · " + backend.version
    Material.theme: backend.settings.theme === "light" ? Material.Light : Material.Dark
    Material.accent: "#72e1c2"
    color: Material.theme === Material.Dark ? "#101925" : "#eef3f8"
    property var draft: JSON.parse(JSON.stringify(backend.settings))
    property int page: 0
    property int macroIndex: -1
    property int profileIndex: -1
    property var catalog: backend.previewCatalog(JSON.stringify(draft))
    property var actionChoices: catalog.filter(a => !['', 'application', 'macros'].includes(a.id)).concat(draft.macros.map(m => ({id: 'macro:' + m.id, name: m.name})), draft.folders.map(f => ({id: 'folder:' + f.id, name: f.name})))
    property string historyId: ''
    property string historyFilter: ""
    property string actionFilter: ""
    property var historyRows: backend.historyEntries.filter(entry => (!actionFilter || entry.displayAction === actionFilter) && ((entry.displayOriginal || '') + (entry.displayResult || '') + entry.displayAction).toLowerCase().includes(historyFilter.toLowerCase()))
    property var historyItem: historyRows.find(entry => entry.id === historyId) || ({})
    function updateDraft() { draft = JSON.parse(JSON.stringify(draft)) }
    function removeMacro() {
        const action = 'macro:' + draft.macros[macroIndex].id
        draft.slots = draft.slots.map((a, i) => { if (a !== action) return a; draft.slotAppearance[i] = {}; return '' })
        draft.folders.forEach(f => f.actions = f.actions.filter(a => a !== action))
        draft.profiles.forEach(p => p.actions = p.actions.filter(a => a !== action))
        draft.bindings = draft.bindings.filter(b => b.action !== action)
        delete draft.appearance[action]
        draft.macros.splice(macroIndex, 1)
        macroIndex = -1
        updateDraft()
    }
    function openPage(name) { page = name === "history" ? 4 : 0; show(); raise(); requestActivate() }
    onClosing: close => { close.accepted = false; hide() }
    Connections { target: backend; function onRequestSettings(name) { window.openPage(name) } }

    RowLayout {
        anchors.fill: parent; spacing: 0
        Rectangle {
            Layout.preferredWidth: 215; Layout.fillHeight: true; color: window.Material.theme === Material.Dark ? "#0c1420" : "#dfe8f0"
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 22; spacing: 7
                Label { text: "◉"; color: "#72e1c2"; font.pixelSize: 38; topPadding: 16 }
                Label { text: "Desktop AI"; font.pixelSize: 24; font.weight: Font.DemiBold }
                Label { text: "YOUR EVERYDAY ACTIONS"; font.pixelSize: 9; font.letterSpacing: 1.3; opacity: 0.5; bottomPadding: 32 }
                Repeater {
                    model: ["Overview", "Languages", "Action ring", "Macros", "App profiles", "History", "Connections"]
                    delegate: Button {
                        required property string modelData
                        required property int index
                        property int targetPage: [0, 6, 1, 2, 3, 4, 5][index]
                        text: modelData; Layout.fillWidth: true; flat: window.page !== targetPage; highlighted: window.page === targetPage
                        onClicked: window.page = targetPage
                    }
                }
                Item { Layout.fillHeight: true }
                Label {
                    objectName: "updateIndicator"
                    text: updates.tone === "muted" ? "WINDOWS PREVIEW  " + backend.version : updates.text.toUpperCase()
                    font.pixelSize: 9; opacity: updates.tone === "muted" ? 0.5 : 0.9
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: window.page = 0 }
                }
                Label { text: "Local history · your AI account"; font.pixelSize: 10; opacity: 0.6 }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; Layout.margins: 28; spacing: 14
            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    Label { text: ["Make room for better words.", "One ring. Your actions.", "Build a useful sequence.", "The right tools for each app.", "Every edit has a way back.", "Connect your workspace.", "Make every language your own."][window.page]; font.pixelSize: 27; font.weight: Font.DemiBold }
                    Label { text: ["Translate, correct and act without leaving your editor.", "Select a segment to view its settings.", "Steps run in order and stop on the first error.", "Global positions stay fixed. The application segment adapts.", "Originals and results are encrypted for this Windows account.", "Use your existing CLI subscription and browser.", "Choose the provider, style and rules for text actions."][window.page]; opacity: 0.6; font.pixelSize: 12 }
                }
                Item { Layout.fillWidth: true }
                Button { objectName: "saveButton"; text: "Save"; highlighted: true; visible: window.page !== 4; onClicked: backend.saveSettings(JSON.stringify(window.draft)) }
            }
            StackLayout {
                currentIndex: window.page; Layout.fillWidth: true; Layout.fillHeight: true
                ScrollView {
                    clip: true; contentWidth: availableWidth
                    ColumnLayout {
                        width: parent.width; spacing: 14
                        GroupBox {
                            title: "Activation"; Layout.fillWidth: true
                            GridLayout {
                                columns: 2; anchors.fill: parent; columnSpacing: 20
                                Label { text: "Open action ring" }
                                ShortcutField { text: window.draft.hotkey; Layout.fillWidth: true; onEditingFinished: window.draft.hotkey = text }
                                Label { text: "Stop running action" }
                                ShortcutField { text: window.draft.stopHotkey; Layout.fillWidth: true; onEditingFinished: window.draft.stopHotkey = text }
                                Label { text: "MX Vertical" }
                                Label { text: "Assign the same shortcut to its top button in Logi Options+."; wrapMode: Text.WordWrap; Layout.fillWidth: true; opacity: 0.7 }
                            }
                        }
                        GroupBox {
                            title: "Appearance & behavior"; Layout.fillWidth: true
                            GridLayout {
                                anchors.fill: parent; columns: 2; columnSpacing: 20
                                Label { text: "Theme" }
                                ComboBox { objectName: "themeChoice"; implicitContentWidthPolicy: ComboBox.WidestText; model: ["dark", "light", "contrast"]; currentIndex: model.indexOf(window.draft.theme); onActivated: window.draft.theme = currentText }
                                Label { text: "Ring size" }
                                ComboBox { objectName: "sizeChoice"; implicitContentWidthPolicy: ComboBox.WidestText; model: ["Compact", "Comfortable", "Large"]; currentIndex: [0.85, 1, 1.2].indexOf(window.draft.size); onActivated: window.draft.size = [0.85, 1, 1.2][currentIndex] }
                                CheckBox { text: "Reduced motion"; checked: window.draft.reducedMotion; onToggled: window.draft.reducedMotion = checked }
                                CheckBox { text: "Start with Windows"; checked: window.draft.autostart; onToggled: window.draft.autostart = checked }
                                Label { text: "History days" }
                                SpinBox { objectName: "historyDays"; from: 1; to: 365; value: window.draft.historyDays; onValueModified: window.draft.historyDays = value }
                            }
                        }
                        UpdatePanel { Layout.fillWidth: true }
                        RowLayout {
                            Button { text: "Export settings"; onClicked: backend.exportSettings() }
                            Button { text: "Preview import"; onClicked: { const value = backend.importSettings(); if (value) window.draft = JSON.parse(value) } }
                            Button { text: "Reset draft"; onClicked: window.draft = JSON.parse(backend.defaults()) }
                        }
                        Label { text: "Exports include saved snippets. Import replaces settings only after Save; it runs no actions."; opacity: 0.6; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                    }
                }
                RingEditor { draft: window.draft; onEdited: value => window.draft = value }
                RowLayout {
                    ColumnLayout {
                        Layout.preferredWidth: 185; Layout.maximumWidth: 200; Layout.fillHeight: true
                        ListView {
                            Layout.fillWidth: true; Layout.fillHeight: true; clip: true; model: window.draft.macros; spacing: 5
                            delegate: Button { required property var modelData; required property int index; width: ListView.view.width; text: modelData.name; flat: window.macroIndex !== index; onClicked: window.macroIndex = index }
                        }
                        Button { text: "+ New macro"; onClicked: { window.draft.macros.push({id: 'macro' + Date.now(), name: 'New macro', steps: [{type: 'delay', value: 0.2}]}); window.updateDraft(); window.macroIndex = window.draft.macros.length - 1 } }
                    }
                    ScrollView {
                        id: macroScroll
                        Layout.fillWidth: true; Layout.fillHeight: true; clip: true; contentWidth: availableWidth; topPadding: 8
                        ColumnLayout {
                            width: macroScroll.availableWidth; spacing: 12; visible: window.macroIndex >= 0 && window.macroIndex < window.draft.macros.length
                            property var macro: visible ? window.draft.macros[window.macroIndex] : ({name: '', steps: []})
                            TextField { Layout.fillWidth: true; Layout.topMargin: 10; text: parent.macro.name; placeholderText: "Macro name"; onEditingFinished: { window.draft.macros[window.macroIndex].name = text; window.updateDraft() } }
                            Repeater {
                                model: parent.macro.steps
                                delegate: Frame {
                                    id: stepFrame
                                    objectName: "macroStep" + index
                                    required property var modelData
                                    required property int index
                                    Layout.fillWidth: true
                                    contentItem: ColumnLayout {
                                        spacing: 10
                                        RowLayout {
                                            StepHandle { stepIndex: index }
                                            Label { text: (index + 1) + "."; opacity: 0.6 }
                                            ComboBox { model: ['keys', 'text', 'open', 'activate', 'delay', 'ai', 'app']; currentIndex: model.indexOf(modelData.type); onActivated: { const step = window.draft.macros[window.macroIndex].steps[index]; step.type = currentText; step.value = currentText === 'delay' ? 0.5 : currentText === 'ai' ? 'english_formal' : currentText === 'app' ? 'jamat_new' : ''; window.updateDraft() } }
                                            Item { Layout.fillWidth: true }
                                            Button { text: "↑"; enabled: index > 0; onClicked: { const steps = window.draft.macros[window.macroIndex].steps; const old = steps[index-1]; steps[index-1] = steps[index]; steps[index] = old; window.updateDraft() } }
                                            Button { text: "×"; onClicked: { window.draft.macros[window.macroIndex].steps.splice(index, 1); window.updateDraft() } }
                                        }
                                        TextArea { Layout.fillWidth: true; Layout.minimumHeight: 90; visible: ['text', 'open', 'activate'].includes(modelData.type); text: String(modelData.value); placeholderText: modelData.type === 'text' ? 'Text to insert' : modelData.type === 'activate' ? 'Target process, for example notepad.exe' : 'Application, file or website'; wrapMode: TextEdit.Wrap; onTextChanged: if (activeFocus) window.draft.macros[window.macroIndex].steps[index].value = text }
                                        ShortcutField { Layout.fillWidth: true; visible: modelData.type === 'keys'; text: String(modelData.value); onEditingFinished: window.draft.macros[window.macroIndex].steps[index].value = text }
                                        SpinBox { visible: modelData.type === 'delay'; from: 0; to: 600; value: modelData.type === 'delay' ? Number(modelData.value) * 10 : 0; textFromValue: value => (value / 10).toFixed(1) + ' seconds'; onValueModified: window.draft.macros[window.macroIndex].steps[index].value = value / 10 }
                                        ComboBox { objectName: 'macroStepAction' + index; Layout.fillWidth: true; visible: ['ai', 'app'].includes(modelData.type); model: window.actionChoices.filter(a => modelData.type === 'ai' ? a.edit : ['jamat_new', 'jamat_remarkable'].includes(a.id)); textRole: 'name'; valueRole: 'id'; currentIndex: model.findIndex(a => a.id === modelData.value); onActivated: window.draft.macros[window.macroIndex].steps[index].value = currentValue }
                                        Label { visible: modelData.type === 'keys' && String(modelData.value).toLowerCase().includes('enter'); text: "This explicit Enter step may send a message."; color: "#efb86d" }
                                    }
                                    DropArea {
                                        parent: stepFrame
                                        anchors.fill: parent; keys: ['macro-step']
                                        onDropped: drop => {
                                            const from = drop.source.stepIndex, to = index
                                            Qt.callLater(() => { const steps = window.draft.macros[window.macroIndex].steps; const moved = steps.splice(from, 1)[0]; steps.splice(to, 0, moved); window.updateDraft() })
                                            drop.acceptProposedAction()
                                        }
                                    }
                                }
                            }
                            RowLayout {
                                objectName: "macroActions"
                                Button { text: "+ Step"; onClicked: { window.draft.macros[window.macroIndex].steps.push({type: 'delay', value: 0.2}); window.updateDraft() } }
                                Button { text: "Run saved macro…"; onClicked: backend.armMacro(window.draft.macros[window.macroIndex].id) }
                                Button { text: "Delete"; onClicked: window.removeMacro() }
                            }
                            Label { text: "Run executes real steps after you focus a target and press the menu shortcut.\nOpening an app does not change the target; add Activate with its process filename."; opacity: 0.65; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                        }
                    }
                }
                ScrollView {
                    clip: true; contentWidth: availableWidth
                    ColumnLayout {
                        width: parent.width
                        Repeater {
                            model: window.draft.profiles
                            delegate: GroupBox {
                                id: profileBox
                                required property var modelData
                                required property int index
                                property int profileRow: index
                                title: modelData.name; Layout.fillWidth: true
                                ColumnLayout {
                                    anchors.fill: parent
                                    RowLayout {
                                        TextField { text: modelData.name; placeholderText: "Profile name"; onEditingFinished: window.draft.profiles[index].name = text }
                                        TextField { text: modelData.process; placeholderText: "process.exe"; Layout.fillWidth: true; onEditingFinished: window.draft.profiles[index].process = text }
                                        Button { text: "Duplicate"; onClicked: { let p = JSON.parse(JSON.stringify(modelData)); p.id = 'profile' + Date.now(); p.name += ' copy'; window.draft.profiles.push(p); window.updateDraft() } }
                                        Button { text: "×"; onClicked: { window.draft.profiles.splice(index, 1); window.updateDraft() } }
                                    }
                                    Repeater {
                                        model: modelData.actions
                                        delegate: RowLayout {
                                            required property string modelData
                                            required property int index
                                            ComboBox { Layout.fillWidth: true; model: window.actionChoices; textRole: 'name'; valueRole: 'id'; currentIndex: model.findIndex(a => a.id === modelData); onActivated: { window.draft.profiles[profileBox.profileRow].actions[index] = currentValue; window.updateDraft() } }
                                            Button { text: '×'; onClicked: { window.draft.profiles[profileBox.profileRow].actions.splice(index, 1); window.updateDraft() } }
                                        }
                                    }
                                    Button { text: '+ Action'; enabled: modelData.actions.length < 6; onClicked: { window.draft.profiles[index].actions.push('english_formal'); window.updateDraft() } }
                                }
                            }
                        }
                        Button { text: "+ App profile"; onClicked: { window.draft.profiles.push({id: 'profile' + Date.now(), name: 'New profile', process: '', actions: ['english']}); window.updateDraft() } }
                        Label { text: "Direct action shortcuts"; font.pixelSize: 18; topPadding: 18 }
                        Repeater {
                            model: window.draft.bindings
                            delegate: RowLayout {
                                required property var modelData
                                required property int index
                                ShortcutField { text: modelData.key; placeholderText: "Ctrl+Alt+E"; onEditingFinished: window.draft.bindings[index].key = text }
                                ComboBox { objectName: 'shortcutAction' + index; Layout.fillWidth: true; model: window.actionChoices.filter(a => !a.group && !a.id.startsWith('folder:')); textRole: 'name'; valueRole: 'id'; currentIndex: model.findIndex(a => a.id === modelData.action); onActivated: window.draft.bindings[index].action = currentValue }
                                ComboBox { Layout.fillWidth: true; model: [{id: '', name: 'All apps'}].concat(window.draft.profiles); textRole: 'name'; valueRole: 'id'; currentIndex: model.findIndex(a => a.id === (modelData.profile || '')); onActivated: window.draft.bindings[index].profile = currentValue }
                                Button { text: "×"; onClicked: { window.draft.bindings.splice(index, 1); window.updateDraft() } }
                            }
                        }
                        Button { text: "+ Shortcut"; onClicked: { window.draft.bindings.push({key: '', action: 'english_formal', profile: ''}); window.updateDraft() } }
                        Label { text: "An app-specific shortcut takes priority over the same shortcut assigned to All apps."; wrapMode: Text.WordWrap; opacity: 0.6; Layout.fillWidth: true }
                    }
                }
                RowLayout {
                    ColumnLayout {
                        Layout.preferredWidth: 230; Layout.fillHeight: true
                        TextField { Layout.fillWidth: true; placeholderText: "Search history"; onTextChanged: { window.historyFilter = text; window.historyId = '' } }
                        ComboBox { Layout.fillWidth: true; model: ['All actions'].concat([...new Set(backend.historyEntries.map(entry => entry.displayAction))]); onActivated: { window.actionFilter = currentIndex ? currentText : ''; window.historyId = '' } }
                        ListView {
                            Layout.fillWidth: true; Layout.fillHeight: true; model: window.historyRows; spacing: 6; clip: true
                            delegate: ItemDelegate { required property var modelData; required property int index; width: ListView.view.width; height: 72; highlighted: window.historyId === modelData.id; onClicked: window.historyId = modelData.id
                                contentItem: Column { spacing: 5; Label { text: modelData.displayAction; font.weight: Font.DemiBold } Label { text: modelData.status + ' · ' + new Date(modelData.created * 1000).toLocaleTimeString(); font.pixelSize: 11; opacity: 0.6 } }
                            }
                        }
                        Button { text: "Clear history…"; enabled: !backend.busy; onClicked: clearDialog.open() }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        Label { text: window.historyItem.source || 'Select an edit'; font.pixelSize: 18 }
                        Label { text: window.historyItem.error || ''; visible: !!text; color: '#efb86d'; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                        Label { text: "ORIGINAL"; opacity: 0.5; font.pixelSize: 10; font.letterSpacing: 1.5 }
                        ScrollView { Layout.fillWidth: true; Layout.fillHeight: true; TextArea { text: window.historyItem.displayOriginal || ''; readOnly: true; wrapMode: TextEdit.Wrap; selectByMouse: true } }
                        Label { text: "RESULT"; opacity: 0.5; font.pixelSize: 10; font.letterSpacing: 1.5 }
                        ScrollView { Layout.fillWidth: true; Layout.fillHeight: true; TextArea { text: window.historyItem.displayResult || ''; readOnly: true; wrapMode: TextEdit.Wrap; selectByMouse: true } }
                        RowLayout {
                            Button { text: "Copy original"; enabled: !!window.historyItem.id; onClicked: backend.copyHistory(window.historyItem.id, true) }
                            Button { text: "Copy result"; enabled: !!window.historyItem.result; onClicked: backend.copyHistory(window.historyItem.id, false) }
                            Button { text: "Restore…"; enabled: window.historyItem.status === 'applied'; onClicked: backend.restore(window.historyItem.id) }
                        }
                    }
                }
                ScrollView {
                    clip: true; contentWidth: availableWidth
                    ColumnLayout {
                        width: parent.width; spacing: 12
                        GroupBox {
                            title: "AI accounts"; Layout.fillWidth: true
                            ColumnLayout {
                                anchors.fill: parent
                                Repeater {
                                    model: ['claude', 'codex']
                                    delegate: RowLayout {
                                        required property string modelData
                                        Label { text: modelData; Layout.preferredWidth: 70 }
                                        TextField { Layout.fillWidth: true; text: window.draft.models[modelData]; placeholderText: "Default model from your account"; onEditingFinished: window.draft.models[modelData] = text }
                                        Button { text: "Sign in"; enabled: !backend.busy; onClicked: backend.login(modelData) }
                                    }
                                }
                                Label { text: "Codex uses a separate app login. No API-key fallback. Text is sent to the selected provider."; opacity: 0.6; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                            }
                        }
                        GroupBox {
                            title: "Chrome / Gmail"; Layout.fillWidth: true
                            ColumnLayout {
                                anchors.fill: parent
                                Label { text: "In chrome://extensions, enable Developer mode, click Load unpacked and select this folder:"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                TextField { objectName: "extensionFolder"; text: backend.extensionPath; readOnly: true; selectByMouse: true; Layout.fillWidth: true; Accessible.name: "Extension installation folder" }
                                RowLayout {
                                    Button { text: "Open folder"; onClicked: backend.openExtensionFolder() }
                                    Button { text: "Copy path"; onClicked: backend.copyExtensionPath() }
                                }
                                Label { text: "Then open the extension and enable Gmail or another site. Reload that page."; wrapMode: Text.WordWrap; Layout.fillWidth: true; opacity: 0.7 }
                                Label { text: backend.browserSetupStatus; wrapMode: Text.WordWrap; Layout.fillWidth: true; color: '#72e1c2' }
                            }
                        }
                        GroupBox {
                            title: "Jamat"; Layout.fillWidth: true
                            ColumnLayout {
                                anchors.fill: parent
                                TextField { Layout.fillWidth: true; text: window.draft.jamat.cli; placeholderText: "Full path to jamat-v3.mjs"; onEditingFinished: window.draft.jamat.cli = text }
                                TextField { Layout.fillWidth: true; text: window.draft.jamat.directory; placeholderText: "Project directory for New session"; onEditingFinished: window.draft.jamat.directory = text }
                                TextField { Layout.fillWidth: true; text: window.draft.jamat.controller; placeholderText: "Controller identity (blank for single-controller discovery)"; onEditingFinished: window.draft.jamat.controller = text }
                                Label { text: "Read from reMarkable is disabled until Jamat provides a verified command."; color: '#efb86d'; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                            }
                        }
                        Button { text: "Check connections"; enabled: !backend.busy; onClicked: backend.diagnostics() }
                        Label { text: "Local data: " + backend.dataPath; opacity: 0.6; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
                    }
                }
                LanguageSettings { draft: window.draft; onEdited: value => window.draft = value }
            }
            Rectangle {
                objectName: "statusPanel"
                implicitHeight: statusRow.implicitHeight + 24
                Layout.fillWidth: true; Layout.preferredHeight: implicitHeight; Layout.minimumHeight: implicitHeight; radius: 10; color: window.Material.theme === Material.Dark ? '#1c2a3a' : '#dce6ef'
                RowLayout {
                    id: statusRow
                    anchors.fill: parent; anchors.margins: 12
                    BusyIndicator { running: backend.busy; visible: running; padding: 0; Layout.preferredWidth: 24; Layout.preferredHeight: 24 }
                    Label { id: statusLabel; text: backend.status; textFormat: Text.PlainText; wrapMode: Text.WordWrap; Layout.fillWidth: true; font.pixelSize: 12 }
                    Button { objectName: "statusStop"; text: "Stop"; visible: backend.busy; onClicked: backend.cancel() }
                }
            }
        }
    }
    Dialog { id: clearDialog; title: "Delete all local history?"; modal: true; anchors.centerIn: parent; standardButtons: Dialog.Ok | Dialog.Cancel; onAccepted: backend.clearHistory(); Label { text: "Originals and saved results will be removed." } }
}
