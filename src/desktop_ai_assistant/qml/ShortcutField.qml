import QtQuick
import QtQuick.Controls

TextField {
    id: field
    property bool recording: false
    readOnly: true
    placeholderText: "Click to record shortcut"
    Accessible.name: "Record keyboard shortcut"
    onActiveFocusChanged: {
        recording = activeFocus
        backend.captureShortcut(activeFocus)
    }
    Keys.onPressed: event => {
        event.accepted = true
        if ([Qt.Key_Control, Qt.Key_Alt, Qt.Key_Shift, Qt.Key_Meta].includes(event.key)) return
        let key = ''
        if (event.key >= Qt.Key_A && event.key <= Qt.Key_Z || event.key >= Qt.Key_0 && event.key <= Qt.Key_9) key = String.fromCharCode(event.key)
        else if (event.key >= Qt.Key_F1 && event.key <= Qt.Key_F24) key = 'F' + (event.key - Qt.Key_F1 + 1)
        else {
            const special = {}; special[Qt.Key_Space] = 'Space'; special[Qt.Key_Escape] = 'Escape'; special[Qt.Key_Return] = 'Enter'; special[Qt.Key_Tab] = 'Tab'; special[Qt.Key_Delete] = 'Delete'; special[Qt.Key_Home] = 'Home'; special[Qt.Key_End] = 'End'; special[Qt.Key_Left] = 'Left'; special[Qt.Key_Right] = 'Right'; special[Qt.Key_Up] = 'Up'; special[Qt.Key_Down] = 'Down'
            key = special[event.key] || ''
        }
        if (!key) return
        const modifiers = []
        if (event.modifiers & Qt.ControlModifier) modifiers.push('Ctrl')
        if (event.modifiers & Qt.AltModifier) modifiers.push('Alt')
        if (event.modifiers & Qt.ShiftModifier) modifiers.push('Shift')
        if (event.modifiers & Qt.MetaModifier) modifiers.push('Win')
        modifiers.push(key); text = modifiers.join('+'); editingFinished(); focus = false
    }
}
