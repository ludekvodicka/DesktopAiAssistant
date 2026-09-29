import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

RowLayout {
    id: editor
    objectName: "ringEditor"
    required property var draft
    signal edited(var value)
    property int selectedSlot: 0
    property bool customizing: false
    property var folderPath: []
    property string pickerFolder: ""
    property int pickerIndex: -1
    readonly property string action: draft.slots[selectedSlot]
    readonly property var selected: backend.previewAction(action, JSON.stringify(draft))
    readonly property var folder: folderPath.length ? draft.folders.find(f => f.id === folderPath[folderPath.length - 1]) : null
    readonly property var shownChildren: folder ? folder.actions.map(a => backend.previewAction(a, JSON.stringify(draft))) : backend.previewChildren(action, JSON.stringify(draft))
    readonly property var choices: backend.catalog.map(a => ({id: a.id, name: a.id === 'english_formal' ? 'English · Formal' : a.id === 'english_social' ? 'English · Social' : a.name + (['english', 'macros', 'application', 'system'].includes(a.id) ? ' (submenu)' : '')})).concat(draft.macros.map(m => ({id: 'macro:' + m.id, name: m.name + ' (macro)'})), draft.folders.map(f => ({id: 'folder:' + f.id, name: f.name + ' (submenu)'})))
    spacing: 20

    function commit() { edited(JSON.parse(JSON.stringify(draft))) }
    function selectSlot(index) {
        selectedSlot = index
        folderPath = action.startsWith('folder:') ? [action.slice(7)] : []
    }
    function pick(folderId, index) { pickerFolder = folderId; pickerIndex = index; search.text = ''; picker.open() }
    function assign(id) {
        if (pickerFolder) {
            const target = draft.folders.find(f => f.id === pickerFolder)
            if (pickerIndex < 0) target.actions.push(id)
            else target.actions[pickerIndex] = id
        } else {
            draft.slots[selectedSlot] = id
            draft.slotAppearance[selectedSlot] = {}
            folderPath = id.startsWith('folder:') ? [id.slice(7)] : []
        }
        commit(); picker.close()
    }
    function createFolder() {
        const id = 'folder' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6)
        draft.folders.push({id: id, name: 'New submenu', icon: '▦', actions: []})
        const inside = !!pickerFolder
        assign('folder:' + id)
        if (inside) folderPath = folderPath.concat([id])
    }
    function createsCycle(id, visited) {
        if (!id.startsWith('folder:')) return false
        const folderId = id.slice(7)
        if (folderId === pickerFolder || visited.includes(folderId)) return true
        const item = draft.folders.find(f => f.id === folderId)
        return item ? item.actions.some(a => createsCycle(a, visited.concat([folderId]))) : false
    }
    function moveChild(index, delta) {
        const list = folder.actions
        const item = list.splice(index, 1)[0]
        list.splice(index + delta, 0, item)
        commit()
    }
    function deleteFolder() {
        const id = 'folder:' + folder.id
        draft.slots = draft.slots.map((a, i) => { if (a !== id) return a; draft.slotAppearance[i] = {}; return '' })
        draft.folders = draft.folders.filter(f => 'folder:' + f.id !== id)
        draft.folders.forEach(f => f.actions = f.actions.filter(a => a !== id))
        draft.profiles.forEach(p => p.actions = p.actions.filter(a => a !== id))
        delete draft.appearance[id]
        folderPath = folderPath.slice(0, -1)
        commit()
    }
    onActionChanged: folderPath = action.startsWith('folder:') ? [action.slice(7)] : []

    ColumnLayout {
        Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumWidth: 300; spacing: 12
        Label { text: 'YOUR RING'; font.pixelSize: 10; font.letterSpacing: 2; opacity: 0.6; Layout.alignment: Qt.AlignHCenter }
        Item {
            Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 300; clip: true
            Ring {
                objectName: "editorRing"
                anchors.centerIn: parent; preview: true
                scale: Math.min(parent.width / 350, parent.height / 350, 1.2)
                selectedIndex: editor.selectedSlot
                items: backend.previewMenu(JSON.stringify(editor.draft))
                onSlotClicked: index => editor.selectSlot(index)
            }
        }
        Label { text: 'Changes become active after Save.'; opacity: 0.5; font.pixelSize: 11; Layout.alignment: Qt.AlignHCenter }
    }

    ScrollView {
        id: detailsScroll
        Layout.preferredWidth: 335; Layout.maximumWidth: 370; Layout.fillHeight: true
        clip: true; contentWidth: availableWidth; topPadding: 8
        rightPadding: 12
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
    ScrollBar.vertical: ScrollBar { orientation: Qt.Vertical; x: parent.width - width; y: 0; height: parent.height; policy: ScrollBar.AsNeeded; active: true; width: 6; contentItem: Rectangle { implicitWidth: 6; radius: 3; color: '#657c91' } }
        ColumnLayout {
            width: detailsScroll.availableWidth; spacing: 12
            Label { text: 'SEGMENT ' + (editor.selectedSlot + 1).toString().padStart(2, '0'); font.pixelSize: 10; font.letterSpacing: 2; opacity: 0.6 }
            Label { text: editor.selected.name || 'Empty segment'; font.pixelSize: 22; font.bold: true; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            Button { objectName: 'chooseSegmentAction'; text: editor.action ? 'Change action…' : 'Choose action…'; highlighted: !editor.action; Layout.fillWidth: true; onClicked: editor.pick('', -1) }
            Label { visible: !editor.action; text: 'Choose a direct action, a macro or a submenu containing your own actions.'; Layout.fillWidth: true; wrapMode: Text.WordWrap; opacity: 0.7 }
            Button { visible: !!editor.action; text: (editor.customizing ? '▾' : '▸') + '  Segment name / icon'; flat: true; Layout.fillWidth: true; onClicked: editor.customizing = !editor.customizing }
            GroupBox {
                title: 'This segment'; visible: !!editor.action && editor.customizing; Layout.fillWidth: true
                contentItem: ColumnLayout {
                    spacing: 8
                    TextField { objectName: 'segmentName'; Layout.fillWidth: true; text: editor.draft.slotAppearance[editor.selectedSlot].name || ''; placeholderText: editor.selected.name; maximumLength: 80; onEditingFinished: { editor.draft.slotAppearance[editor.selectedSlot].name = text; editor.commit() } }
                    TextField { objectName: 'segmentIcon'; Layout.fillWidth: true; text: editor.draft.slotAppearance[editor.selectedSlot].icon || ''; placeholderText: 'Icon: ' + editor.selected.icon; maximumLength: 8; onEditingFinished: { editor.draft.slotAppearance[editor.selectedSlot].icon = text; editor.commit() } }
                    Button { text: 'Clear segment'; flat: true; onClicked: { editor.pickerFolder = ''; editor.assign('') } }
                }
            }
            GroupBox {
                title: editor.folder ? 'Edit submenu' : 'Submenu contents'
                visible: !!editor.folder || editor.selected.group; Layout.fillWidth: true
                contentItem: ColumnLayout {
                    spacing: 8
                    Button { visible: editor.folderPath.length > 1; text: '‹ Parent submenu'; onClicked: editor.folderPath = editor.folderPath.slice(0, -1) }
                    RowLayout {
                        visible: !!editor.folder
                        TextField { objectName: 'folderName'; Layout.fillWidth: true; text: editor.folder ? editor.folder.name : ''; placeholderText: 'Submenu name'; maximumLength: 80; onEditingFinished: { if (editor.folder) { editor.folder.name = text; editor.commit() } } }
                        TextField { Layout.preferredWidth: 60; text: editor.folder ? editor.folder.icon : ''; placeholderText: 'Icon'; maximumLength: 8; onEditingFinished: { if (editor.folder) { editor.folder.icon = text; editor.commit() } } }
                    }
                    Label { visible: !editor.folder; text: 'This built-in submenu is filled automatically. Choose “New submenu” for your own collection.'; Layout.fillWidth: true; wrapMode: Text.WordWrap; opacity: 0.65 }
                    Repeater {
                        model: editor.shownChildren
                        delegate: RowLayout {
                            required property var modelData
                            required property int index
                            Layout.fillWidth: true; spacing: 2
                            ItemDelegate { objectName: 'folderItem' + index; text: modelData.name; Layout.fillWidth: true; enabled: !!editor.folder; onClicked: editor.pick(editor.folder.id, index) }
                            ToolButton { text: '›'; visible: modelData.id.startsWith('folder:'); Layout.preferredWidth: 28; leftPadding: 4; rightPadding: 4; Accessible.name: 'Open submenu'; onClicked: editor.folderPath = editor.folderPath.concat([modelData.id.slice(7)]) }
                            ToolButton { text: '↑'; visible: !!editor.folder; Layout.preferredWidth: 28; leftPadding: 4; rightPadding: 4; enabled: index > 0; Accessible.name: 'Move up'; onClicked: editor.moveChild(index, -1) }
                            ToolButton { text: '↓'; visible: !!editor.folder; Layout.preferredWidth: 28; leftPadding: 4; rightPadding: 4; enabled: index < editor.shownChildren.length - 1; Accessible.name: 'Move down'; onClicked: editor.moveChild(index, 1) }
                            ToolButton { text: '×'; visible: !!editor.folder; Layout.preferredWidth: 28; leftPadding: 4; rightPadding: 4; Accessible.name: 'Remove item'; onClicked: { editor.folder.actions.splice(index, 1); editor.commit() } }
                        }
                    }
                    Button { objectName: 'addFolderItem'; visible: !!editor.folder; enabled: !!editor.folder && editor.shownChildren.length < 6; text: '+ Add item'; Layout.fillWidth: true; onClicked: editor.pick(editor.folder.id, -1) }
                    Label { visible: !!editor.folder; text: editor.shownChildren.length + ' / 6 items'; opacity: 0.5; font.pixelSize: 11 }
                    Button { visible: !!editor.folder; text: 'Delete submenu…'; flat: true; onClicked: deleteDialog.open() }
                }
            }
        }
    }

    Dialog {
        id: picker
        objectName: 'actionPicker'
        title: editor.pickerFolder ? 'Choose a submenu item' : 'Choose an action · Segment ' + (editor.selectedSlot + 1)
        modal: true; anchors.centerIn: Overlay.overlay
        implicitWidth: 520
        background: Rectangle { color: backend.settings.theme === 'light' ? '#f6f8fc' : '#172233'; radius: 16; border.color: '#3c5068' }
        Overlay.modal: Rectangle { color: '#99050b12' }
        width: Math.min(520, Overlay.overlay.width - 48); height: Math.min(600, Overlay.overlay.height - 48)
        standardButtons: Dialog.Cancel
        header: Label { text: picker.title; font.pixelSize: 23; padding: 24; wrapMode: Text.WordWrap }
        footer: DialogButtonBox { standardButtons: Dialog.Cancel; background: Item {} }
        contentItem: ColumnLayout {
            spacing: 10
            TextField { id: search; objectName: 'actionSearch'; placeholderText: 'Search actions, macros and submenus'; Layout.fillWidth: true }
            Button { objectName: 'newFolder'; text: '+ New submenu'; highlighted: true; Layout.fillWidth: true; onClicked: editor.createFolder() }
            ListView {
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 4
                model: editor.choices.filter(a => (!editor.pickerFolder || a.id && a.id !== 'application' && !editor.createsCycle(a.id, [])) && a.name.toLowerCase().includes(search.text.toLowerCase()))
                ScrollBar.vertical: ScrollBar {}
                delegate: ItemDelegate {
                    required property var modelData
                    width: ListView.view.width
                    text: (modelData.id.startsWith('folder:') ? '▦  ' : '') + modelData.name
                    onClicked: editor.assign(modelData.id)
                }
            }
        }
    }

    Dialog {
        id: deleteDialog
        title: 'Delete this submenu?'; modal: true; anchors.centerIn: Overlay.overlay
        standardButtons: Dialog.Ok | Dialog.Cancel
        Label { text: 'The submenu is removed from all segments and folders.\nIts actions remain available in the action picker.' }
        onAccepted: editor.deleteFolder()
    }
}
