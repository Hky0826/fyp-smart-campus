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
    property bool verifying: false
    property string errorText: ""

    signal closeRequested()
    signal messageRequested(string message)

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
            anchors.leftMargin: parent.width < 760 ? 16 : 300
            anchors.rightMargin: parent.width < 760 ? 16 : 24
            anchors.topMargin: 24
            anchors.bottomMargin: 24
            spacing: 14

            RowLayout {
                Layout.fillWidth: true
                spacing: 12

                Text {
                    text: "Chatbot"
                    color: "#0f172a"
                    font.pixelSize: 24
                    font.bold: true
                    Layout.fillWidth: true
                }

                Text {
                    text: root.verifying ? "Verifying" : root.sessionName + "  " + root.presenceState
                    color: "#64748b"
                    font.pixelSize: 14
                    elide: Text.ElideRight
                    Layout.maximumWidth: 420
                }

                Button {
                    width: 88
                    height: 54
                    text: "Close"
                    onClicked: root.closeRequested()
                    background: Rectangle { radius: 8; color: "#111827" }
                    contentItem: Text {
                        text: parent.text
                        color: "#ffffff"
                        font.pixelSize: 15
                        font.bold: true
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }

            ListView {
                id: history
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 10
                model: root.messages || []
                onCountChanged: Qt.callLater(function() { history.positionViewAtEnd() })

                delegate: Item {
                    width: history.width
                    height: bubble.implicitHeight

                    Rectangle {
                        id: bubble
                        width: Math.min(parent.width * 0.82, 680)
                        x: modelData.role === "user" ? parent.width - width : 0
                        implicitHeight: messageColumn.implicitHeight + 24
                        radius: 8
                        color: modelData.role === "user" ? "#dbeafe" : modelData.role === "system" ? "#f1f5f9" : "#ecfeff"

                        Column {
                            id: messageColumn
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 12
                            spacing: 8

                            Text {
                                width: parent.width
                                text: String(modelData.content || "")
                                color: modelData.role === "user" ? "#1e3a8a" : modelData.role === "system" ? "#475569" : "#164e63"
                                font.pixelSize: 16
                                wrapMode: Text.WordWrap
                            }

                            Text {
                                width: parent.width
                                visible: modelData.citations && modelData.citations.length > 0
                                text: citationText(modelData.citations)
                                color: "#64748b"
                                font.pixelSize: 12
                                wrapMode: Text.WordWrap
                            }
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                enabled: !root.verifying
                opacity: root.verifying ? 0.45 : 1

                TextField {
                    id: input
                    Layout.fillWidth: true
                    placeholderText: "Ask a question"
                    enabled: !root.busy
                    color: "#0f172a"
                    placeholderTextColor: "#64748b"
                    selectByMouse: true
                    onAccepted: sendText()
                    background: Rectangle {
                        radius: 8
                        color: "#ffffff"
                        border.width: 1
                        border.color: "#d6dee8"
                    }
                }

                Button {
                    width: 82
                    height: 52
                    enabled: input.text.trim().length > 0 && !root.busy
                    text: "Send"
                    onClicked: sendText()
                    background: Rectangle { radius: 8; color: parent.enabled ? "#111827" : "#94a3b8" }
                    contentItem: Text {
                        text: parent.text
                        color: "#ffffff"
                        font.pixelSize: 15
                        font.bold: true
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                enabled: !root.verifying
                opacity: root.verifying ? 0.45 : 1

                Item {
                    id: micIndicator
                    width: 42
                    height: 42
                    Layout.alignment: Qt.AlignVCenter

                    Rectangle {
                        id: micHead
                        x: 14
                        y: 5
                        width: 14
                        height: 22
                        radius: 7
                        color: "transparent"
                        border.width: 3
                        border.color: root.busy ? "#2563eb" : root.listening ? "#0f766e" : "#64748b"
                    }

                    Rectangle {
                        x: 20
                        y: 26
                        width: 3
                        height: 8
                        radius: 2
                        color: root.busy ? "#2563eb" : root.listening ? "#0f766e" : "#64748b"
                    }

                    Rectangle {
                        x: 13
                        y: 34
                        width: 16
                        height: 3
                        radius: 2
                        color: root.busy ? "#2563eb" : root.listening ? "#0f766e" : "#64748b"
                    }

                    SequentialAnimation on y {
                        running: root.listening && !root.busy
                        loops: Animation.Infinite
                        NumberAnimation { to: -5; duration: 260; easing.type: Easing.InOutQuad }
                        NumberAnimation { to: 0; duration: 260; easing.type: Easing.InOutQuad }
                    }

                    RotationAnimation on rotation {
                        running: root.busy
                        loops: Animation.Infinite
                        from: 0
                        to: 360
                        duration: 900
                    }
                }

                Text {
                    text: root.busy ? "Processing audio" : root.listening ? "Listening" : "Microphone standby"
                    color: "#64748b"
                    font.pixelSize: 13
                }

                Row {
                    spacing: 5
                    visible: root.busy
                    Layout.alignment: Qt.AlignVCenter

                    Repeater {
                        model: 3
                        Rectangle {
                            width: 7
                            height: 7
                            radius: 4
                            color: "#2563eb"

                            SequentialAnimation on opacity {
                                running: root.busy
                                loops: Animation.Infinite
                                PauseAnimation { duration: index * 130 }
                                NumberAnimation { to: 0.2; duration: 260 }
                                NumberAnimation { to: 1.0; duration: 260 }
                            }
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: root.errorText
                    visible: root.errorText.length > 0
                    color: "#7f1d1d"
                    font.pixelSize: 13
                    elide: Text.ElideRight
                    horizontalAlignment: Text.AlignRight
                }
            }
        }
    }

    function sendText() {
        var message = input.text.trim()
        if (message.length === 0) {
            return
        }
        input.text = ""
        root.messageRequested(message)
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
