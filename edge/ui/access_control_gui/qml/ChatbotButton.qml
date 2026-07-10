import QtQuick
import QtQuick.Controls

Button {
    id: root
    property string mode: "idle"
    readonly property bool accessResult: mode === "access-granted" || mode === "access-denied"
    readonly property color glowColor: mode === "access-granted" ? "#22c55e" : "#ef4444"

    width: 64
    height: 64
    padding: 0
    text: ""

    background: Rectangle {
        radius: width / 2
        color: root.enabled ? "#f8fafc" : "#94a3b8"
        border.width: root.accessResult ? 3 : 0
        border.color: root.accessResult ? root.glowColor : "transparent"

        Rectangle {
            anchors.centerIn: parent
            width: parent.width + 24
            height: parent.height + 24
            radius: width / 2
            color: "transparent"
            border.width: root.accessResult ? 8 : 0
            border.color: root.accessResult ? root.glowColor : "transparent"
            opacity: root.accessResult ? 0.34 : 0

            SequentialAnimation on opacity {
                running: root.accessResult
                loops: Animation.Infinite
                NumberAnimation { to: 0.12; duration: 520 }
                NumberAnimation { to: 0.34; duration: 520 }
            }
        }
    }

    contentItem: Item {
        Rectangle {
            id: bubble
            anchors.centerIn: parent
            width: 30
            height: 24
            radius: 8
            color: "transparent"
            border.width: 3
            border.color: "#0f172a"
        }

        Rectangle {
            width: 10
            height: 10
            x: bubble.x + 5
            y: bubble.y + bubble.height - 3
            rotation: 45
            color: root.enabled ? "#f8fafc" : "#94a3b8"
            border.width: 3
            border.color: "#0f172a"
        }

        Rectangle {
            width: 14
            height: 8
            x: bubble.x + 2
            y: bubble.y + bubble.height - 5
            color: root.enabled ? "#f8fafc" : "#94a3b8"
        }
    }
}
