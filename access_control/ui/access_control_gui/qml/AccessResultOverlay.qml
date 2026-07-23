import QtQuick

Item {
    id: root
    property string mode: "idle"
    property string titleText: ""
    property string subtitleText: ""
    visible: mode === "access-granted" || mode === "access-denied" || mode === "only-one-person"

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(560, parent.width - 36)
        height: 190
        radius: 8
        color: mode === "access-granted" ? "#e614532d" : "#e67f1d1d"
        border.width: 1
        border.color: mode === "access-granted" ? "#22c55e" : "#ef4444"

        Column {
            anchors.centerIn: parent
            width: parent.width - 40
            spacing: 12

            Text {
                width: parent.width
                text: root.titleText
                color: "#f8fafc"
                font.pixelSize: 42
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
            }

            Text {
                width: parent.width
                text: root.subtitleText
                color: mode === "access-granted" ? "#dcfce7" : "#fee2e2"
                font.pixelSize: 18
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
            }
        }
    }
}

