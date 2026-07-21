import QtQuick
import QtQuick.Controls

Item {
    id: root
    property bool databaseOk: true
    property bool modelsOk: true
    property string errorText: ""
    signal refreshRequested()

    Rectangle {
        anchors.fill: parent
        color: "#ee020617"
    }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(620, parent.width - 36)
        height: 290
        radius: 8
        color: "#f8fafc"

        Column {
            anchors.centerIn: parent
            width: parent.width - 48
            spacing: 14

            Text {
                width: parent.width
                text: "Device setup required"
                color: "#0f172a"
                font.pixelSize: 30
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
            }

            Text {
                width: parent.width
                text: statusText()
                color: "#475569"
                font.pixelSize: 16
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
            }

            Text {
                width: parent.width
                visible: root.errorText.length > 0
                text: root.errorText
                color: "#7f1d1d"
                font.pixelSize: 14
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
            }

            Button {
                anchors.horizontalCenter: parent.horizontalCenter
                width: 150
                height: 48
                text: "Refresh"
                onClicked: root.refreshRequested()
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

    function statusText() {
        var parts = []
        if (!root.databaseOk) {
            parts.push("SQLite database is not initialized or not readable.")
        }
        if (!root.modelsOk) {
            parts.push("Required face-recognition model files are missing.")
        }
        return parts.length ? parts.join(" ") : "Checking device setup."
    }
}

