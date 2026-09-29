import QtQuick

Item {
    id: handle
    property int stepIndex: -1
    width: 28; height: 36
    Rectangle {
        id: badge
        property int stepIndex: handle.stepIndex
        width: 28; height: 36; radius: 6; color: mouse.drag.active ? "#317b68" : "#253b4d"
        Drag.active: mouse.drag.active; Drag.keys: ["macro-step"]; Drag.hotSpot.x: 14; Drag.hotSpot.y: 18
        Text { anchors.centerIn: parent; text: "⠿"; color: "#b7d2e4"; font.pixelSize: 20 }
        MouseArea { id: mouse; anchors.fill: parent; drag.target: badge; cursorShape: Qt.OpenHandCursor; onReleased: { badge.Drag.drop(); badge.x = 0; badge.y = 0 } }
    }
}
