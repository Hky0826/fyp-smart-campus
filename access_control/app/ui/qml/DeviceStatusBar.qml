import QtQuick
import QtQuick.Layouts

Item {
    id: root
    property string deviceName: ""
    property string deviceId: ""
    property bool edgeOnline: false
    property string cloudSync: "unknown"
    property string cloudChatbot: "unknown"

    height: 72

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Math.max(18, parent.width * 0.025)
        anchors.rightMargin: Math.max(18, parent.width * 0.025)
        spacing: 12

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2
            Text {
                text: root.deviceName || "Edge Kiosk"
                color: "#f8fafc"
                font.pixelSize: 18
                font.bold: true
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
            Text {
                text: root.deviceId
                color: "#cbd5e1"
                font.pixelSize: 13
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
        }

        Text {
            text: "Edge " + (root.edgeOnline ? "online" : "offline")
            color: "#e2e8f0"
            font.pixelSize: 13
        }

        Text {
            text: "Sync " + root.cloudSync
            color: "#e2e8f0"
            font.pixelSize: 13
        }

        Text {
            text: "Chat " + root.cloudChatbot
            color: "#e2e8f0"
            font.pixelSize: 13
        }
    }
}
