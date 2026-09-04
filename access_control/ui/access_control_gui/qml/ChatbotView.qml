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
    property bool speaking: false
    property string ragStatus: ""
    property var currentNavigation: null
    property var citations: []
    property bool muted: false
    property bool verifying: false
    property string errorText: ""
    property real outputGain: 0.65

    signal closeRequested()
    signal stopAnsweringRequested()
    signal outputGainChangedRequested(real gain)

    onVisibleChanged: {
        if (visible) {
            history.userScrolledUp = false
            history.scrollToBottom()
        }
    }

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

                // Assistant Speaker Volume / Gain Control
                RowLayout {
                    spacing: 4
                    Text {
                        text: "🔊"
                        font.pixelSize: 13
                    }
                    Slider {
                        id: volumeSlider
                        from: 0.2
                        to: 1.0
                        stepSize: 0.05
                        value: root.outputGain
                        implicitWidth: 80
                        implicitHeight: 28
                        onMoved: root.outputGainChangedRequested(value)
                    }
                    Text {
                        text: Math.round(volumeSlider.value * 100) + "%"
                        color: "#64748b"
                        font.pixelSize: 11
                        font.bold: true
                        Layout.preferredWidth: 32
                    }
                }

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
                boundsBehavior: Flickable.StopAtBounds
                spacing: 8
                model: root.messages || []

                property bool userScrolledUp: false

                function scrollToBottom() {
                    Qt.callLater(function() {
                        history.positionViewAtEnd()
                    })
                }

                onMovementEnded: {
                    if (history.atYEnd || history.contentY >= history.contentHeight - history.height - 30) {
                        userScrolledUp = false
                    } else {
                        userScrolledUp = true
                    }
                }

                onFlickEnded: {
                    if (history.atYEnd || history.contentY >= history.contentHeight - history.height - 30) {
                        userScrolledUp = false
                    } else {
                        userScrolledUp = true
                    }
                }

                onCountChanged: {
                    userScrolledUp = false
                    scrollToBottom()
                }

                onModelChanged: {
                    if (!userScrolledUp) {
                        scrollToBottom()
                    }
                }

                onContentHeightChanged: {
                    if (!userScrolledUp || history.contentHeight <= history.height) {
                        scrollToBottom()
                    }
                }

                Component.onCompleted: {
                    scrollToBottom()
                }

                delegate: Item {
                    width: history.width
                    height: Math.max(1, bubble.implicitHeight)

                    Rectangle {
                        id: bubble
                        width: Math.min(parent.width * 0.86, 540)
                        x: modelData.role === "user" ? parent.width - width : 0
                        implicitHeight: messageColumn.implicitHeight + 16
                        height: implicitHeight
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
                                text: String(modelData.content || "").replace(/\n/g, "\n\n")
                                color: modelData.role === "user" ? "#1e3a8a" : modelData.role === "system" ? "#334155" : "#164e63"
                                font.pixelSize: 14
                                textFormat: Text.MarkdownText
                                wrapMode: Text.WordWrap
                            }

                            Text {
                                width: parent.width
                                visible: modelData.citations && modelData.citations.length > 0 && modelData.role !== "user"
                                text: citationText(modelData.citations)
                                color: "#0369a1"
                                font.pixelSize: 11
                                font.bold: true
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

            // RAG Status Banner (searching indicator)
            Rectangle {
                Layout.fillWidth: true
                height: 28
                radius: 6
                color: "#e0f2fe"
                border.width: 1
                border.color: "#38bdf8"
                visible: root.ragStatus.length > 0

                RowLayout {
                    anchors.centerIn: parent
                    spacing: 6
                    Text {
                        text: "🔍"
                        font.pixelSize: 12
                    }
                    Text {
                        text: root.ragStatus
                        color: "#0369a1"
                        font.pixelSize: 12
                        font.bold: true
                    }
                }
            }

            // Turn-by-Turn Navigation Card (Wayfinding)
            Rectangle {
                id: navCard
                Layout.fillWidth: true
                radius: 8
                color: "#f0fdf4"
                border.width: 1
                border.color: "#86efac"
                visible: root.currentNavigation !== null && root.currentNavigation !== undefined && Object.keys(root.currentNavigation).length > 0
                implicitHeight: navCol.implicitHeight + 16

                ColumnLayout {
                    id: navCol
                    anchors.fill: parent
                    anchors.margins: 8
                    spacing: 4

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        Text {
                            text: "🗺️ Campus Navigation"
                            font.pixelSize: 13
                            font.bold: true
                            color: "#166534"
                        }
                        Item { Layout.fillWidth: true }
                        Text {
                            text: {
                                var sum = root.currentNavigation ? (root.currentNavigation.route_summary || {}) : {}
                                var dist = sum.total_distance_m ? (sum.total_distance_m + " m") : ""
                                var timeLabel = sum.estimated_time_label || ""
                                return dist ? (dist + " (" + timeLabel + ")") : ""
                            }
                            font.pixelSize: 11
                            color: "#15803d"
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        text: {
                            var sum = root.currentNavigation ? (root.currentNavigation.route_summary || {}) : {}
                            var target = root.currentNavigation ? (root.currentNavigation.navigation_target || {}) : {}
                            var dest = target.label || sum.destination_label || "Destination"
                            var start = sum.start_label || "Your location"
                            return start + " ➔ " + dest
                        }
                        font.pixelSize: 12
                        font.bold: true
                        color: "#14532d"
                        elide: Text.ElideRight
                    }

                    Column {
                        Layout.fillWidth: true
                        spacing: 2
                        Repeater {
                            model: (root.currentNavigation && root.currentNavigation.instructions) ? root.currentNavigation.instructions : []
                            RowLayout {
                                width: parent.width
                                spacing: 4
                                Text {
                                    text: (index + 1) + "."
                                    font.pixelSize: 11
                                    font.bold: true
                                    color: "#166534"
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.instruction || ""
                                    font.pixelSize: 11
                                    color: "#1e293b"
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }
                    }
                }
            }

            // Fully Hands-Free Live Voice Status Indicator
            Rectangle {
                id: handsFreeIndicator
                Layout.fillWidth: true
                height: 42
                radius: 8
                color: root.busy ? "#334155" : root.speaking ? "#15803d" : root.listening ? "#0284c7" : "#64748b"

                Behavior on color { ColorAnimation { duration: 200 } }

                RowLayout {
                    anchors.centerIn: parent
                    spacing: 8

                    // Mic Icon Indicator
                    Item {
                        width: 18
                        height: 18
                        visible: !root.busy

                        Rectangle {
                            x: 5
                            y: 1
                            width: 8
                            height: 10
                            radius: 4
                            color: "#ffffff"
                        }
                        Rectangle {
                            x: 3
                            y: 7
                            width: 12
                            height: 6
                            radius: 4
                            color: "transparent"
                            border.width: 2
                            border.color: "#ffffff"
                        }
                        Rectangle {
                            x: 8
                            y: 13
                            width: 2
                            height: 4
                            color: "#ffffff"
                        }
                    }

                    // Speaking / Busy Animation
                    Row {
                        spacing: 4
                        visible: root.busy

                        Repeater {
                            model: 3
                            Rectangle {
                                width: 5
                                height: 5
                                radius: 3
                                color: "#38bdf8"

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

                    Text {
                        text: root.busy
                              ? "Assistant speaking... (Speak to interrupt)"
                              : root.speaking
                              ? "Listening to you..."
                              : root.listening
                              ? "Hands-free voice active — speak naturally at any time"
                              : "Microphone standby"
                        color: "#ffffff"
                        font.pixelSize: 13
                        font.bold: true
                    }

                    // Stop / Interrupt Button (only visible while assistant is answering)
                    Button {
                        visible: root.busy
                        implicitWidth: 64
                        implicitHeight: 28
                        text: "Interrupt"
                        onClicked: root.stopAnsweringRequested()
                        background: Rectangle {
                            radius: 4
                            color: "#ef4444"
                        }
                        contentItem: Text {
                            text: parent.text
                            color: "#ffffff"
                            font.pixelSize: 11
                            font.bold: true
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
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
