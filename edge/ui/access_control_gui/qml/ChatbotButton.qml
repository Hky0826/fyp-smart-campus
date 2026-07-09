import QtQuick
import QtQuick.Controls

Button {
    id: root
    width: 64
    height: 64
    padding: 0
    text: ""

    background: Rectangle {
        radius: width / 2
        color: root.enabled ? "#f8fafc" : "#94a3b8"
        border.width: 0
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
