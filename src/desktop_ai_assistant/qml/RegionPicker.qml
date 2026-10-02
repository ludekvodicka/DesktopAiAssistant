import QtQuick

Window {
    id: overlay
    required property int index
    required property string source
    flags: Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
    color: "black"

    Image { anchors.fill: parent; source: overlay.source; cache: false }
    Rectangle { anchors.fill: parent; color: "#66000000" }
    Rectangle { id: band; visible: false; color: "transparent"; border.color: "#72e1c2"; border.width: 2 }
    MouseArea {
        property point origin
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: Qt.CrossCursor
        onPressed: e => {
            if (e.button === Qt.RightButton) {
                picker.cancel()
                return
            }
            origin = Qt.point(e.x, e.y)
            band.x = e.x; band.y = e.y; band.width = 0; band.height = 0
            band.visible = true
        }
        onPositionChanged: e => {
            band.x = Math.min(origin.x, e.x); band.y = Math.min(origin.y, e.y)
            band.width = Math.abs(e.x - origin.x); band.height = Math.abs(e.y - origin.y)
        }
        onReleased: e => { if (e.button === Qt.LeftButton) picker.finish(overlay.index, band.x, band.y, band.width, band.height) }
    }
    Item { anchors.fill: parent; focus: true; Keys.onEscapePressed: picker.cancel() }
}
