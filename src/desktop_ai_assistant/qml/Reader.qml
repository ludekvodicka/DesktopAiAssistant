import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Window

ApplicationWindow {
    id: reader
    objectName: "reader"
    width: 900; height: 640; minimumWidth: 480; minimumHeight: 300
    visible: false; title: translator.title || "Translate"
    Material.theme: backend.settings.theme === "light" ? Material.Light : Material.Dark
    Material.accent: "#72e1c2"
    color: Material.theme === Material.Dark ? "#101925" : "#eef3f8"
    property bool showOriginal: false
    readonly property bool running: translator.running
    onClosing: close => { close.accepted = false; hide(); translator.closed() }
    Connections { target: translator; function onOpened() { reader.showOriginal = false } }
    Shortcut { sequence: "Esc"; onActivated: reader.close() }

    ColumnLayout {
        anchors.fill: parent; anchors.margins: 16; spacing: 10
        RowLayout {
            Layout.fillWidth: true
            BusyIndicator { running: reader.running; visible: running; Layout.preferredWidth: 28; Layout.preferredHeight: 28 }
            Label { text: translator.title; font.pixelSize: 16; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
        }
        Label {
            objectName: "readerNote"
            text: translator.error || translator.note; visible: !!text; wrapMode: Text.WordWrap; Layout.fillWidth: true
            color: translator.error ? "#efb86d" : reader.Material.foreground; opacity: translator.error ? 1 : 0.75
        }
        SplitView {
            objectName: "readerSplit"
            orientation: Qt.Vertical; Layout.fillWidth: true; Layout.fillHeight: true
            handle: Rectangle {
                implicitHeight: 8; color: "transparent"
                Rectangle {
                    anchors.centerIn: parent; width: 48; height: 3; radius: 2
                    color: parent.SplitHandle.pressed || parent.SplitHandle.hovered ? "#72e1c2" : "#3c5068"
                }
            }
            ScrollView {
                SplitView.fillHeight: true; SplitView.minimumHeight: 60
                TextArea {
                    objectName: "readerText"; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap
                    textFormat: translator.state === 'done' ? TextEdit.RichText : TextEdit.PlainText
                    text: translator.state === 'done' ? (reader.showOriginal ? translator.sourceHtml : translator.resultHtml) : translator.preview
                    onLinkActivated: link => translator.openLink(link)
                }
            }
            ScrollView {
                id: conversation
                objectName: "readerConversationView"
                visible: !!translator.conversationHtml; SplitView.minimumHeight: 60
                // A drag on the handle replaces this binding with the height the user chose.
                SplitView.preferredHeight: Math.min(conversationText.implicitHeight + 8, reader.height * 0.45)
                TextArea {
                    id: conversationText
                    objectName: "readerConversation"; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap
                    textFormat: TextEdit.RichText; text: translator.conversationHtml
                    onLinkActivated: link => translator.openLink(link)
                    // A new answer scrolls into view.
                    onTextChanged: cursorPosition = length
                }
            }
        }
        Label { objectName: "readerAskError"; text: translator.askError; visible: !!text; color: "#efb86d"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
        RowLayout {
            Layout.fillWidth: true; visible: translator.state === 'done'
            TextField {
                id: question
                objectName: "readerQuestion"; placeholderText: "Ask about the text…"; enabled: translator.canAsk; Layout.fillWidth: true
                onAccepted: if (text.trim()) { translator.ask(text); clear() }
            }
            BusyIndicator { running: translator.asking; visible: running; Layout.preferredWidth: 24; Layout.preferredHeight: 24 }
            Button { objectName: "readerAsk"; text: "Ask"; enabled: translator.canAsk && !!question.text.trim(); onClicked: { translator.ask(question.text); question.clear() } }
            Button { objectName: "readerExplain"; text: "Explain"; enabled: translator.canAsk; onClicked: translator.explain() }
        }
        RowLayout {
            Layout.fillWidth: true
            Button { objectName: "readerStop"; text: "Stop"; visible: reader.running || translator.asking; onClicked: translator.stop() }
            Button { objectName: "readerCopy"; text: translator.copyText; highlighted: true; enabled: translator.state === 'done'; onClicked: translator.copy() }
            Button {
                objectName: "readerOriginal"; text: "Show original"; checkable: true; checked: reader.showOriginal
                enabled: translator.state === 'done'; onToggled: reader.showOriginal = checked
            }
            Item { Layout.fillWidth: true }
            Button { objectName: "readerRetry"; text: "Retry"; enabled: translator.canRetry; onClicked: translator.retry() }
        }
    }
}
