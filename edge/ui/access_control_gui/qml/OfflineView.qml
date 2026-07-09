import QtQuick
import QtQuick.Controls

Item {
    id: root
    property string apiBaseUrl: ""
    property string cameraError: ""
    signal retryRequested()

    Rectangle {
        anchors.fill: parent
        color: "#f0020617"
    }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(620, parent.width - 36)
        height: 300
        radius: 8
        color: "#111827"
        border.width: 1
        border.color: "#f87171"

        Column {
            anchors.centerIn: parent
            width: parent.width - 48
            spacing: 14

            Text {
                width: parent.width
                text: "Edge backend offline"
                color: "#f8fafc"
                font.pixelSize: 32
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
            }

            Text {
                width: parent.width
                text: detailText()
                color: "#cbd5e1"
                font.pixelSize: 16
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
            }

            Button {
                anchors.horizontalCenter: parent.horizontalCenter
                width: 150
                height: 48
                text: "Retry"
                onClicked: root.retryRequested()
                background: Rectangle { radius: 8; color: "#f8fafc" }
                contentItem: Text {
                    text: parent.text
                    color: "#0f172a"
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
        }
    }

    function detailText() {
        if (root.cameraError.length > 0) {
            return root.cameraError
        }
        return "Waiting for " + root.apiBaseUrl + ". The camera pipeline remains local, but access and chatbot decisions require the existing edge API."
    }
}

