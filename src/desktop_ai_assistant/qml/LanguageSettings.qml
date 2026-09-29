import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

ScrollView {
    id: languages
    objectName: "languageSettings"
    required property var draft
    signal edited(var value)
    clip: true; contentWidth: availableWidth; topPadding: 8
    rightPadding: 12
    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
    ScrollBar.vertical: ScrollBar { orientation: Qt.Vertical; x: parent.width - width; y: 0; height: parent.height; policy: ScrollBar.AsNeeded; active: true; width: 6; contentItem: Rectangle { implicitWidth: 6; radius: 3; color: '#657c91' } }
    function commit() { edited(JSON.parse(JSON.stringify(draft))) }
    ColumnLayout {
        width: languages.availableWidth; spacing: 16
        GroupBox {
            title: 'Language assistant'; Layout.fillWidth: true
            contentItem: ColumnLayout {
                RowLayout {
                    Label { text: 'AI provider'; Layout.fillWidth: true }
                    ComboBox { model: ['claude', 'codex']; currentIndex: model.indexOf(languages.draft.provider); onActivated: { languages.draft.provider = currentText; languages.commit() } }
                }
                Label { text: 'Fix English translates Czech or mixed text into English. Opravit češtinu produces corrected Czech.'; Layout.fillWidth: true; wrapMode: Text.WordWrap; opacity: 0.7 }
                CheckBox { text: 'Keep social English lowercase'; checked: languages.draft.socialLowercase; onToggled: { languages.draft.socialLowercase = checked; languages.commit() } }
            }
        }
        Repeater {
            model: [{id: 'english_formal', name: 'Fix English · Formal', description: 'Professional wording, grammar and capitalization.'}, {id: 'english_social', name: 'Fix English · Social', description: 'Natural chat wording while preserving tone and emoji.'}, {id: 'czech', name: 'Opravit češtinu', description: 'Czech grammar, diacritics and punctuation.'}]
            delegate: GroupBox {
                required property var modelData
                title: modelData.name; Layout.fillWidth: true
                contentItem: ColumnLayout {
                    spacing: 8
                    Label { text: modelData.description; opacity: 0.7; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                    TextArea { objectName: 'rules_' + modelData.id; Layout.fillWidth: true; Layout.minimumHeight: 85; text: languages.draft.rules[modelData.id]; placeholderText: 'Additional instructions (optional)'; wrapMode: TextEdit.Wrap; onTextChanged: if (activeFocus) { languages.draft.rules[modelData.id] = text; languages.commit() } }
                }
            }
        }
    }
}
