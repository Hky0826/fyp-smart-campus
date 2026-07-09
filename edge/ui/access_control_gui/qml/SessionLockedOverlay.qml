import QtQuick
import QtQuick.Controls

Item {
    id: root
    property string presenceState: "UNKNOWN"
    signal endRequested()

    Rectangle {
        anchors.fill: parent
        color: "#cc020617"
    }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(520, parent.width - 36)
        height: 220
        radius: 8
        color: "#f8fafc"
        border.width: 1
        border.color: "#f59e0b"

        Column {
            anchors.centerIn: parent
            width: parent.width - 48
            spacing: 14

            Text {
                width: parent.width
                text: "Session locked"
                color: "#0f172a"
                font.pixelSize: 30
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
            }

            Text {
                width: parent.width
                text: "Owner presence state: " + root.presenceState
                color: "#64748b"
                font.pixelSize: 16
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
            }

            Button {
                anchors.horizontalCenter: parent.horizontalCenter
                width: 160
                height: 48
                text: "End session"
                onClicked: root.endRequested()
                background: Rectangle { radius: 8; color: "#111827" }
                contentItem: Text {
                    text: parent.text
                    color: "#ffffff"
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
        }
    }
}

