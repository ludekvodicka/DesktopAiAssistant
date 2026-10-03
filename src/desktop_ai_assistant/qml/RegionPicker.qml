import QtQuick

Window {
    id: overlay
    required property int index
    required property string source
    flags: Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
    color: "black"

    Image { anchors.fill: parent; source: overlay.source; cache: false }
    Rectangle { anchors.fill: parent; color: "#66000000" }
    Rectangle { id: band; objectName: "regionBand"; visible: false; color: "transparent"; border.color: "#72e1c2"; border.width: 2 }
    Rectangle {
        anchors.top: parent.top; anchors.horizontalCenter: parent.horizontalCenter; anchors.topMargin: 16
        width: hint.implicitWidth + 24; height: hint.implicitHeight + 16; radius: 6; color: "#dd172233"
        Text { id: hint; anchors.centerIn: parent; text: "Drag to select · Hold Ctrl to move · Esc to cancel"; color: "#ffffff"; font.pixelSize: 14 }
    }
    MouseArea {
        id: drag
        property point origin
        property point end
        property point previous
        property bool moving: false
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: moving ? Qt.SizeAllCursor : Qt.CrossCursor
        function updateSelection(e) {
            if (!(pressedButtons & Qt.LeftButton)) return
            let dx = e.x - previous.x, dy = e.y - previous.y
            moving = !!(e.modifiers & Qt.ControlModifier)
            if (moving) {
                dx = Math.max(-Math.min(origin.x, end.x), Math.min(width - Math.max(origin.x, end.x), dx))
                dy = Math.max(-Math.min(origin.y, end.y), Math.min(height - Math.max(origin.y, end.y), dy))
                origin = Qt.point(origin.x + dx, origin.y + dy)
                end = Qt.point(end.x + dx, end.y + dy)
            } else
                end = Qt.point(Math.max(0, Math.min(width, end.x + dx)), Math.max(0, Math.min(height, end.y + dy)))
            previous = Qt.point(e.x, e.y)
            band.x = Math.min(origin.x, end.x); band.y = Math.min(origin.y, end.y)
            band.width = Math.abs(end.x - origin.x); band.height = Math.abs(end.y - origin.y)
        }
        onPressed: e => {
            if (e.button === Qt.RightButton) {
                picker.cancel()
                return
            }
            origin = Qt.point(e.x, e.y)
            end = origin; previous = origin
            moving = !!(e.modifiers & Qt.ControlModifier)
            band.x = e.x; band.y = e.y; band.width = 0; band.height = 0
            band.visible = true
        }
        onPositionChanged: e => updateSelection(e)
        onReleased: e => { if (e.button === Qt.LeftButton) picker.finish(overlay.index, band.x, band.y, band.width, band.height) }
    }
    Item { anchors.fill: parent; focus: true; Keys.onEscapePressed: picker.cancel() }
}
