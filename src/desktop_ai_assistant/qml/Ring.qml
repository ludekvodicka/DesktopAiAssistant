import QtQuick
import QtQuick.Shapes

Item {
    id: root
    width: 600; height: 600
    property int hovered: -1
    property int childHover: -1
    property int variantHover: -1
    property bool preview: false
    property int selectedIndex: -1
    signal slotClicked(int index)
    property var items: backend.menu
    property var submenuItems: preview ? [] : backend.children
    property var variantItems: preview ? [] : backend.variants
    readonly property real innerRadius: root.items[0].inner
    readonly property real outerRadius: root.items[0].outer
    readonly property bool light: backend.settings.theme === "light"
    readonly property color panel: light ? "#f6f8fc" : "#172233"
    readonly property color ink: light ? "#18283c" : "#e8f0fa"
    readonly property color border: light ? "#bac9d8" : "#3c5068"
    readonly property color accent: backend.settings.theme === "contrast" ? "#ffff00" : "#72e1c2"
    scale: backend.settings.size
    opacity: 1
    Behavior on opacity { NumberAnimation { duration: backend.settings.reducedMotion ? 0 : 130 } }

    Rectangle { x: 300 - root.outerRadius; y: x; width: root.outerRadius * 2; height: width; radius: root.outerRadius; color: "#19000000" }
    Repeater {
        model: root.items
        delegate: Item {
            required property var modelData
            required property int index
            anchors.fill: parent
            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeWidth: 1.4
                    strokeColor: (hovered === index || root.selectedIndex === index) && (modelData.enabled || root.preview) ? root.accent : root.border
                    fillColor: (hovered === index || root.selectedIndex === index) && (modelData.enabled || root.preview) ? (root.light ? "#c6f3e6" : "#24534d") : (modelData.enabled ? root.panel : (root.light ? "#e6ebf2" : "#131d2b"))
                    PathSvg { path: modelData.path }
                }
            }
            Column {
                x: modelData.x - 46; y: modelData.y - 27; width: 92; spacing: 5
                Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: modelData.id ? (modelData.icon === "⚙" ? "⚙︎" : modelData.icon) : "·"; font.family: modelData.icon === "⚙" ? "Segoe UI Symbol" : Qt.application.font.family; color: modelData.enabled ? root.accent : "#60738a"; font.pixelSize: 23; font.weight: Font.Medium }
                Text { width: parent.width; text: modelData.id ? modelData.name : ""; color: modelData.enabled ? root.ink : "#77899f"; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight }
            }
        }
    }
    Rectangle {
        x: 232; y: 232; width: 136; height: 136; radius: 68; color: root.light ? "#ffffff" : "#0e1724"; border.color: root.border
        Column {
            anchors.centerIn: parent; spacing: 8; width: 116
            Rectangle { width: 6; height: 6; radius: 3; color: root.accent; anchors.horizontalCenter: parent.horizontalCenter }
            Text { text: backend.busy ? "WORKING" : "DESKTOP AI"; font.pixelSize: 10; font.letterSpacing: 1.5; color: root.accent; anchors.horizontalCenter: parent.horizontalCenter }
            Text { text: "v" + backend.version; width: parent.width; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 12; color: root.ink }
            Text { text: root.preview ? "SELECT A SEGMENT" : backend.canGoBack ? "← BACK" : "ESC TO CLOSE"; font.pixelSize: 8; font.letterSpacing: 1; color: "#8094ab"; anchors.horizontalCenter: parent.horizontalCenter }
        }
    }
    component Sector: Item {
        required property var modelData
        required property int index
        property bool lit
        property string prefix
        anchors.fill: parent
        Shape {
            anchors.fill: parent; preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeWidth: 1.4; strokeColor: lit ? root.accent : root.border
                fillColor: lit ? (root.light ? "#c6f3e6" : "#24534d") : root.panel
                PathSvg { path: modelData.path }
            }
        }
        Column {
            x: modelData.x - width / 2; y: modelData.y - height / 2 - 6; width: modelData.labelWidth; spacing: 4
            Text { width: parent.width; text: modelData.icon === "⚙" ? "⚙︎" : modelData.icon; font.family: modelData.icon === "⚙" ? "Segoe UI Symbol" : Qt.application.font.family; color: modelData.enabled ? root.accent : "#66798e"; font.pixelSize: 20; horizontalAlignment: Text.AlignHCenter }
            Text { objectName: prefix + index; width: parent.width; text: modelData.name; color: modelData.enabled ? root.ink : "#66798e"; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight }
        }
    }
    Repeater {
        model: root.submenuItems
        delegate: Sector { lit: root.childHover === index; prefix: "submenuLabel" }
    }
    Repeater {
        model: root.variantItems
        delegate: Sector { lit: root.variantHover === index; prefix: "variantLabel" }
    }
    MouseArea {
        anchors.fill: parent; hoverEnabled: true
        function sectorAt(items, x, y) {
            for (let i = 0; i < items.length; i++) {
                const item = items[i]
                const dx = x - item.cx, dy = y - item.cy
                let a = Math.atan2(dy, dx) * 180 / Math.PI
                while (a < item.start) a += 360
                const r = Math.hypot(dx, dy)
                if (r >= item.inner && r <= item.outer && a <= item.end) return i
            }
            return -1
        }
        function hit(x, y) {
            root.variantHover = sectorAt(root.variantItems, x, y)
            if (root.variantHover >= 0) { childTimer.stop(); return }
            root.childHover = sectorAt(root.submenuItems, x, y)
            if (root.childHover >= 0) { childTimer.restart(); return }
            const radius = Math.hypot(x - 300, y - 300)
            if (radius >= root.innerRadius && radius <= root.outerRadius) {
                const a = (Math.atan2(y - 300, x - 300) * 180 / Math.PI + 112.5 + 360) % 360
                root.hovered = Math.floor(a / 45)
                if (!root.preview) submenuTimer.restart()
            } else if (radius < root.innerRadius) {
                root.hovered = -1
            }
        }
        onPositionChanged: mouse => hit(mouse.x, mouse.y)
        onClicked: mouse => {
            hit(mouse.x, mouse.y)
            if (root.preview) {
                if (root.hovered >= 0 && Math.hypot(mouse.x - 300, mouse.y - 300) <= root.outerRadius) root.slotClicked(root.hovered)
                return
            }
            if (root.variantHover >= 0) {
                const variant = backend.variants[root.variantHover]
                if (variant.enabled) backend.execute(variant.id)
            } else if (root.childHover >= 0) {
                const child = backend.children[root.childHover]
                if (child.enabled && child.group) backend.enterChild(root.childHover)
                else if (child.enabled) backend.execute(child.id)
            } else if (root.hovered >= 0 && Math.hypot(mouse.x - 300, mouse.y - 300) <= root.outerRadius) {
                const item = backend.menu[root.hovered]
                if (item.enabled && !item.group) backend.execute(item.id)
                else backend.hover(root.hovered)
            } else if (Math.hypot(mouse.x - 300, mouse.y - 300) < root.innerRadius && backend.canGoBack) backend.backFolder()
            else backend.hideMenu()
        }
    }
    Timer { id: submenuTimer; interval: 140; onTriggered: backend.hover(root.hovered) }
    Timer { id: childTimer; interval: 140; onTriggered: if (root.childHover >= 0) backend.hoverChild(root.childHover) }
}
