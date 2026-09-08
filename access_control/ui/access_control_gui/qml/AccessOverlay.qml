import QtQuick
import QtQuick.Layouts

Item {
    id: root
    property string titleText: ""
    property string subtitleText: ""
    property string mode: "idle"
    property string cameraError: ""
    property real dwellProgress: 0.0

    width: Math.min(560, parent.width - 36)
    height: panel.implicitHeight

    Rectangle {
        id: panel
        width: parent.width
        implicitHeight: content.implicitHeight + 28
        radius: 8
        color: root.mode === "access-denied" ? "#cc7f1d1d" : root.mode === "access-granted" ? "#cc14532d" : "#aa0f172a"
        border.width: 1
        border.color: root.mode === "access-denied" ? "#f87171" : root.mode === "access-granted" ? "#22c55e" : "#33ffffff"

        ColumnLayout {
            id: content
            anchors.fill: parent
            anchors.margins: 14
            spacing: 8

            Text {
                text: root.titleText
                color: "#f8fafc"
                font.pixelSize: 28
                font.bold: true
                elide: Text.ElideRight
                Layout.fillWidth: true
            }

            Text {
                text: root.cameraError ? root.cameraError : root.subtitleText
                color: root.cameraError ? "#fecaca" : "#cbd5e1"
                font.pixelSize: 16
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            Rectangle {
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: 6
                width: 150
                height: 190
                radius: 76
                color: "transparent"
                border.width: root.dwellProgress > 0.0 ? 3 : 2
                border.color: root.dwellProgress > 0.0 ? "#38bdf8" : "#88ffffff"
                visible: root.mode === "idle" || root.mode === "chat-verifying" || root.mode === "access-verifying"

                Behavior on border.color {
                    ColorAnimation { duration: 250 }
                }
                Behavior on border.width {
                    NumberAnimation { duration: 250 }
                }
            }
        }
    }
}

