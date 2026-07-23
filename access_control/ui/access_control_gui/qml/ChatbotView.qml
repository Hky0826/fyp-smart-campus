import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property var messages: []
    property string sessionName: "Visitor"
    property string presenceState: "UNKNOWN"
    property bool listening: false
    property bool busy: false
    property bool muted: false
    property bool verifying: false
    property string errorText: ""

    signal closeRequested()
    signal pushToTalkStarted()
    signal pushToTalkStopped()
    signal pushToTalkToggled()

    Rectangle {
        anchors.fill: parent
        color: "#f8fafc"
    }

    Rectangle {
        id: windowPanel
        anchors.fill: parent
        radius: 0
        color: "#f8fafc"

        ColumnLayout {
            anchors.fill: parent
            anchors.leftMargin: parent.width <= 800 ? 12 : 280
            anchors.rightMargin: 12
            anchors.topMargin: 10
            anchors.bottomMargin: 10
            spacing: 8

            // Header Bar (Compact for 800x480)
            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Text {
                    text: "Chatbot"
                    color: "#0f172a"
                    font.pixelSize: 18
                    font.bold: true
                }

                Rectangle {
                    radius: 12
                    color: root.verifying ? "#fef3c7" : "#e0f2fe"
                    implicitWidth: statusText.implicitWidth + 14
                    implicitHeight: 24

                    Text {
                        id: statusText
                        anchors.centerIn: parent
                        text: root.verifying ? "Verifying..." : root.sessionName + " (" + root.presenceState + ")"
                        color: root.verifying ? "#92400e" : "#0369a1"
                        font.pixelSize: 11
                        font.bold: true
                    }
                }

                Item { Layout.fillWidth: true }

                Button {
                    implicitWidth: 68
                    implicitHeight: 34
                    text: "Close"
                    onClicked: root.closeRequested()
                    background: Rectangle { radius: 6; color: "#1e293b" }
                    contentItem: Text {
                        text: parent.text
                        color: "#ffffff"
                        font.pixelSize: 13
                        font.bold: true
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }

            // Message History Area
            ListView {
                id: history
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 8
                model: root.messages || []
                onCountChanged: Qt.callLater(function() { history.positionViewAtEnd() })

                delegate: Item {
                    width: history.width
                    height: bubble.implicitHeight

                    Rectangle {
                        id: bubble
                        width: Math.min(parent.width * 0.86, 540)
                        x: modelData.role === "user" ? parent.width - width : 0
                        implicitHeight: messageColumn.implicitHeight + 16
                        radius: 8
                        color: modelData.role === "user" ? "#dbeafe" : modelData.role === "system" ? "#f1f5f9" : "#ecfeff"
                        border.width: 1
                        border.color: modelData.role === "user" ? "#bfdbfe" : modelData.role === "system" ? "#e2e8f0" : "#a5f3fc"

                        Column {
                            id: messageColumn
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 8
                            spacing: 4

                            Text {
                                width: parent.width
                                text: String(modelData.content || "")
                                color: modelData.role === "user" ? "#1e3a8a" : modelData.role === "system" ? "#334155" : "#164e63"
                                font.pixelSize: 14
                                wrapMode: Text.WordWrap
                            }

                            Text {
                                width: parent.width
                                visible: modelData.citations && modelData.citations.length > 0
                                text: citationText(modelData.citations)
                                color: "#64748b"
                                font.pixelSize: 11
                                wrapMode: Text.WordWrap
                            }
                        }
                    }
                }
            }

            // Error display if present
            Text {
                Layout.fillWidth: true
                text: root.errorText
                visible: root.errorText.length > 0
                color: "#dc2626"
                font.pixelSize: 11
                elide: Text.ElideRight
                horizontalAlignment: Text.AlignHCenter
            }

            // Push to Speak Controls (Optimized for 5-inch 800x480 touch display)
            Rectangle {
                id: pttButton
                Layout.fillWidth: true
                height: 46
                radius: 8
                enabled: !root.verifying
                opacity: root.verifying ? 0.5 : 1.0

                color: root.busy ? "#475569" : root.listening ? "#dc2626" : "#0284c7"

                Behavior on color { ColorAnimation { duration: 150 } }

                // Pulse Animation while listening
                Rectangle {
                    anchors.fill: parent
                    radius: parent.radius
                    color: "transparent"
                    border.width: 3
                    border.color: "#ef4444"
                    visible: root.listening

                    SequentialAnimation on opacity {
                        running: root.listening
                        loops: Animation.Infinite
                        NumberAnimation { to: 0.2; duration: 400 }
                        NumberAnimation { to: 1.0; duration: 400 }
                    }
                }

                RowLayout {
                    anchors.centerIn: parent
                    spacing: 8

                    // Mic Icon Indicator
                    Item {
                        width: 20
                        height: 20

                        Rectangle {
                            x: 6
                            y: 2
                            width: 8
                            height: 11
                            radius: 4
                            color: "#ffffff"
                        }
                        Rectangle {
                            x: 4
                            y: 8
                            width: 12
                            height: 7
                            radius: 4
                            color: "transparent"
                            border.width: 2
                            border.color: "#ffffff"
                        }
                        Rectangle {
                            x: 9
                            y: 15
                            width: 2
                            height: 4
                            color: "#ffffff"
                        }
                    }

                    Text {
                        text: root.busy ? "Processing audio..." : root.listening ? "Listening... Release/Tap to Send" : "Hold or Tap to Speak"
                        color: "#ffffff"
                        font.pixelSize: 14
                        font.bold: true
                    }

                    // Processing Spinner Dots
                    Row {
                        spacing: 4
                        visible: root.busy

                        Repeater {
                            model: 3
                            Rectangle {
                                width: 5
                                height: 5
                                radius: 3
                                color: "#ffffff"

                                SequentialAnimation on opacity {
                                    running: root.busy
                                    loops: Animation.Infinite
                                    PauseAnimation { duration: index * 120 }
                                    NumberAnimation { to: 0.2; duration: 250 }
                                    NumberAnimation { to: 1.0; duration: 250 }
                                }
                            }
                        }
                    }
                }

                MouseArea {
                    id: pttMouseArea
                    anchors.fill: parent
                    enabled: !root.busy && !root.verifying

                    property bool heldMode: false

                    Timer {
                        id: holdTimer
                        interval: 220
                        repeat: false
                        onTriggered: {
                            pttMouseArea.heldMode = true
                            root.pushToTalkStarted()
                        }
                    }

                    onPressed: {
                        pttMouseArea.heldMode = false
                        holdTimer.start()
                    }

                    onReleased: {
                        holdTimer.stop()
                        if (pttMouseArea.heldMode) {
                            root.pushToTalkStopped()
                        }
                    }

                    onClicked: {
                        if (!pttMouseArea.heldMode) {
                            if (root.listening) {
                                root.pushToTalkStopped()
                            } else {
                                root.pushToTalkStarted()
                            }
                        }
                        pttMouseArea.heldMode = false
                    }
                }
            }
        }
    }

    function citationText(citations) {
        if (!citations || citations.length === 0) {
            return ""
        }
        var labels = []
        for (var i = 0; i < Math.min(citations.length, 3); i++) {
            var citation = citations[i]
            labels.push(citation.document_title || citation.title || citation.chunk_id || ("Source " + (i + 1)))
        }
        return "Sources: " + labels.join(", ")
    }
}
