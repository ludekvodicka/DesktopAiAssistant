import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: toast
    width: 420
    height: content.implicitHeight + 32
    color: backend.settings.theme === "light" ? "#f6f8fc" : "#172233"
    radius: 12
    border.color: failed ? "#efb86d" : "#3c5068"
    property bool failed: false
    // The edit lane wins the toast; a translation shows here only while no edit runs.
    readonly property bool translating: !backend.busy && translator.running
    signal dismissed()
    readonly property color ink: backend.settings.theme === "light" ? "#18283c" : "#e8f0fa"
    readonly property color accent: backend.settings.theme === "light" ? "#15765e" : "#72e1c2"
    ColumnLayout {
        id: content
        x: 16; y: 16; width: parent.width - 32; spacing: 10
        RowLayout {
            BusyIndicator { running: (backend.busy && !backend.waitingForEditor) || toast.translating; visible: running; padding: 0; Layout.preferredWidth: 22; Layout.preferredHeight: 22 }
            Text { text: backend.waitingForEditor ? "Desktop AI · Result ready" : backend.busy ? "Desktop AI · Working" : toast.translating ? "Desktop AI · " + translator.progressText : toast.failed ? "Desktop AI · Action stopped" : "Desktop AI"; color: toast.failed ? "#efb86d" : toast.accent; font.pixelSize: 13; font.bold: true; Layout.fillWidth: true }
            Text { text: "×"; color: toast.ink; font.pixelSize: 22; MouseArea { anchors.fill: parent; anchors.margins: -6; onClicked: toast.dismissed() } }
        }
        Text { text: toast.translating ? translator.title : backend.status; textFormat: Text.PlainText; color: toast.ink; font.pixelSize: 13; wrapMode: Text.WordWrap; maximumLineCount: 6; elide: Text.ElideRight; Layout.fillWidth: true }
        RowLayout {
            Item { Layout.fillWidth: true }
            Text {
                text: backend.waitingForEditor ? "Cancel insertion" : backend.busy ? "Stop action" : toast.translating ? translator.stopText : "Open history"
                color: toast.accent; font.pixelSize: 12
                MouseArea { anchors.fill: parent; anchors.margins: -4; cursorShape: Qt.PointingHandCursor; onClicked: { if (backend.busy) backend.cancel(); else if (toast.translating) translator.stop(); else backend.requestSettings("history"); toast.dismissed() } }
            }
        }
    }
}
