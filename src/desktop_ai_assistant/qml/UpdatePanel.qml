import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

GroupBox {
    objectName: "updatePanel"
    title: "Updates"
    ColumnLayout {
        anchors.fill: parent; spacing: 8
        Label { objectName: "updateText"; text: updates.text; font.bold: true; color: ({muted: "#9aa7b4", working: "#72b7e1", attention: "#e1b572", ready: "#72e1c2", failed: "#e17272"})[updates.tone] }
        Label { text: updates.detail; visible: text.length > 0; wrapMode: Text.Wrap; opacity: 0.7; Layout.fillWidth: true }
        TextArea { objectName: "updateNotes"; text: updates.notes; visible: text.length > 0; readOnly: true; textFormat: TextEdit.PlainText; wrapMode: TextEdit.Wrap; Layout.fillWidth: true; Layout.maximumHeight: 220 }
        RowLayout {
            Button { objectName: "updateCheck"; text: "Check now"; visible: updates.actions.indexOf("check") >= 0; onClicked: updates.check() }
            Button { objectName: "updateInstall"; text: "Restart and install"; highlighted: true; visible: updates.actions.indexOf("install") >= 0; onClicked: updates.install() }
            Button { objectName: "updateRelease"; text: "View on GitHub"; visible: updates.actions.indexOf("open_release") >= 0; onClicked: updates.openReleasePage() }
        }
    }
}
