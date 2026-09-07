import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    width: 800
    height: 480

    property var messages: []
    property string sessionName: "Alex Tan"
    property string presenceState: "In Frame"
    property bool listening: false
    property bool busy: false
    property bool speaking: false
    property real userAudioLevel: 0.0
    property real assistantAudioLevel: 0.0
    property string ragStatus: ""
    property var currentNavigation: null
    property var citations: []
    property bool muted: false
    property bool verifying: false
    property string errorText: ""

    signal closeRequested()
    signal stopAnsweringRequested()
    signal toggleMuteRequested()

    onVisibleChanged: {
        if (visible) {
            history.userScrolledUp = false
            history.scrollToBottom()
        }
    }

    function getInitials(name) {
        if (!name || name === "Visitor") return "AT"
        var parts = name.trim().split(" ")
        if (parts.length === 1) return parts[0].substring(0, 2).toUpperCase()
        return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
    }

    // ==========================================
    // 1. LEFT DOCK (25% / 200px width, 480px height)
    // ==========================================
    Rectangle {
        id: leftDock
        x: 0
        y: 0
        width: 200
        height: root.height
        color: "#e2e8f0" // Preview: bg-slate-200
        border.width: 1
        border.color: "#cbd5e1" // Preview: border-slate-300

        // Live Camera Feed Box with Glowing Cyan Accent
        // (Sits under CameraView which is docked at x:10, y:10, 180x118, z:35)
        Rectangle {
            id: cameraSlot
            x: 10
            y: 10
            width: 180
            height: 118
            radius: 8
            color: "#020617" // Preview: bg-slate-950
            border.width: 2
            border.color: "#22d3ee" // Preview: border-cyan-400

            // Live Verification Pill (Bottom Left)
            Rectangle {
                anchors.bottom: parent.bottom
                anchors.left: parent.left
                anchors.margins: 6
                radius: 4
                color: "#059669" // Preview: bg-emerald-600
                implicitWidth: verPillRow.implicitWidth + 10
                implicitHeight: 18
                z: 40

                Row {
                    id: verPillRow
                    anchors.centerIn: parent
                    spacing: 4

                    Rectangle {
                        width: 5
                        height: 5
                        radius: 3
                        color: "#ffffff"
                        anchors.verticalCenter: parent.verticalCenter
                        SequentialAnimation on opacity {
                            loops: Animation.Infinite
                            NumberAnimation { to: 0.3; duration: 500 }
                            NumberAnimation { to: 1.0; duration: 500 }
                        }
                    }

                    Text {
                        text: "Verified"
                        color: "#ffffff"
                        font.pixelSize: 9
                        font.bold: true
                    }
                }
            }

            // Accuracy guide pill (Top Left)
            Rectangle {
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.margins: 6
                radius: 3
                color: "#0891b2" // Preview: bg-cyan-600
                implicitWidth: 26
                implicitHeight: 14
                z: 40

                Text {
                    anchors.centerIn: parent
                    text: "98%"
                    color: "#ffffff"
                    font.pixelSize: 8
                    font.bold: true
                }
            }
        }

        // Authenticated User Profile Card
        Rectangle {
            id: userCard
            x: 10
            y: 136
            width: 180
            height: 84
            radius: 8
            color: "#ffffff" // Preview: bg-white
            border.width: 1
            border.color: "#e2e8f0" // Preview: border-slate-200

            Column {
                anchors.fill: parent
                anchors.margins: 8
                spacing: 5

                RowLayout {
                    width: parent.width
                    spacing: 8

                    // Colorful Gradient Avatar
                    Rectangle {
                        width: 30
                        height: 30
                        radius: 15
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0.0; color: "#9333ea" } // purple-600
                            GradientStop { position: 1.0; color: "#6366f1" } // indigo-500
                        }

                        Text {
                            anchors.centerIn: parent
                            text: root.getInitials(root.sessionName)
                            color: "#ffffff"
                            font.pixelSize: 11
                            font.bold: true
                        }
                    }

                    Column {
                        Layout.fillWidth: true
                        spacing: 2

                        Text {
                            width: parent.width
                            text: root.sessionName
                            color: "#0f172a" // slate-900
                            font.pixelSize: 12
                            font.bold: true
                            elide: Text.ElideRight
                        }

                        Rectangle {
                            radius: 3
                            color: "#4f46e5" // Preview: bg-indigo-600
                            implicitWidth: roleText.implicitWidth + 8
                            implicitHeight: 16

                            Text {
                                id: roleText
                                anchors.centerIn: parent
                                text: root.verifying ? "VERIFYING" : "STUDENT"
                                color: "#ffffff"
                                font.pixelSize: 8
                                font.bold: true
                            }
                        }
                    }
                }

                // Security Status Row
                Rectangle {
                    width: parent.width
                    height: 1
                    color: "#f1f5f9"
                }

                RowLayout {
                    width: parent.width
                    Text {
                        text: "Security:"
                        color: "#64748b" // slate-500
                        font.pixelSize: 9
                    }
                    Item { Layout.fillWidth: true }
                    Row {
                        spacing: 4
                        Rectangle {
                            width: 6
                            height: 6
                            radius: 3
                            color: "#10b981" // emerald-500
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: "In Frame"
                            color: "#059669" // emerald-600
                            font.pixelSize: 9
                            font.bold: true
                        }
                    }
                }
            }
        }

        // ==========================================
        // DUAL REACTIVE VOICE CHANNELS CARD
        // (Replaces Speaker Volume - Reacts to Live User Voice & Chatbot Voice)
        // ==========================================
        Rectangle {
            id: voiceChannelsCard
            x: 10
            y: 228
            width: 180
            height: 172
            radius: 8
            color: "#ffffff"
            border.width: 1
            border.color: "#e2e8f0"

            Column {
                anchors.fill: parent
                anchors.margins: 8
                spacing: 6

                // Header
                RowLayout {
                    width: parent.width
                    Text {
                        text: "VOICE CHANNELS"
                        color: "#64748b"
                        font.pixelSize: 9
                        font.bold: true
                        font.letterSpacing: 0.5
                    }
                    Item { Layout.fillWidth: true }
                    Rectangle {
                        radius: 3
                        color: "#eef2ff"
                        border.width: 1
                        border.color: "#c7d2fe"
                        implicitWidth: duplexBadgeText.implicitWidth + 6
                        implicitHeight: 15

                        Text {
                            id: duplexBadgeText
                            anchors.centerIn: parent
                            text: "LIVE"
                            color: "#4338ca"
                            font.pixelSize: 8
                            font.bold: true
                        }
                    }
                }

                // Channel 1: YOUR LIVE VOICE (MIC IN)
                Column {
                    width: parent.width
                    spacing: 4

                    RowLayout {
                        width: parent.width
                        Row {
                            spacing: 4
                            Text {
                                text: "🎙️"
                                font.pixelSize: 11
                            }
                            Text {
                                text: "You (Mic)"
                                color: "#0f172a"
                                font.pixelSize: 11
                                font.bold: true
                            }
                        }
                        Item { Layout.fillWidth: true }
                        Rectangle {
                            radius: 10
                            color: root.speaking ? "#dcfce7" : (root.listening && !root.muted ? "#e0f2fe" : "#fee2e2")
                            implicitWidth: userVoiceTag.implicitWidth + 8
                            implicitHeight: 16

                            Text {
                                id: userVoiceTag
                                anchors.centerIn: parent
                                text: root.speaking ? "Speaking" : (root.listening && !root.muted ? "Listening" : "Muted")
                                color: root.speaking ? "#166534" : (root.listening && !root.muted ? "#0369a1" : "#dc2626")
                                font.pixelSize: 8
                                font.bold: true
                            }
                        }
                    }

                    // 8-Bar Reactive Waveform (Reacts to user's live voice)
                    Row {
                        spacing: 3
                        anchors.horizontalCenter: parent.horizontalCenter
                        height: 24

                        Repeater {
                            model: [
                                { "color": "#06b6d4", "maxH": 16, "dur": 260 },
                                { "color": "#0891b2", "maxH": 22, "dur": 210 },
                                { "color": "#0284c7", "maxH": 26, "dur": 280 },
                                { "color": "#2563eb", "maxH": 24, "dur": 230 },
                                { "color": "#3b82f6", "maxH": 20, "dur": 250 },
                                { "color": "#4f46e5", "maxH": 26, "dur": 220 },
                                { "color": "#6366f1", "maxH": 18, "dur": 270 },
                                { "color": "#06b6d4", "maxH": 14, "dur": 240 }
                            ]
                            Rectangle {
                                width: 3
                                radius: 2
                                color: modelData.color
                                anchors.verticalCenter: parent.verticalCenter
                                height: root.speaking ? Math.max(6, modelData.maxH * Math.max(0.35, root.userAudioLevel)) : 3

                                Behavior on height {
                                    NumberAnimation { duration: 80 }
                                }

                                SequentialAnimation on height {
                                    running: root.speaking
                                    loops: Animation.Infinite
                                    NumberAnimation { to: Math.max(8, modelData.maxH * Math.max(0.4, root.userAudioLevel)); duration: modelData.dur }
                                    NumberAnimation { to: 4; duration: modelData.dur }
                                }
                            }
                        }
                    }
                }

                Rectangle {
                    width: parent.width
                    height: 1
                    color: "#f1f5f9"
                }

                // Channel 2: CHATBOT VOICE (AI RESPONSE OUT)
                Column {
                    width: parent.width
                    spacing: 4

                    RowLayout {
                        width: parent.width
                        Row {
                            spacing: 4
                            Text {
                                text: "🤖"
                                font.pixelSize: 11
                            }
                            Text {
                                text: "Campus AI"
                                color: "#0f172a"
                                font.pixelSize: 11
                                font.bold: true
                            }
                        }
                        Item { Layout.fillWidth: true }
                        Rectangle {
                            radius: 10
                            color: root.busy ? "#f3e8ff" : "#f1f5f9"
                            implicitWidth: aiVoiceTag.implicitWidth + 8
                            implicitHeight: 16

                            Text {
                                id: aiVoiceTag
                                anchors.centerIn: parent
                                text: root.busy ? "Responding" : "Standby"
                                color: root.busy ? "#6b21a8" : "#64748b"
                                font.pixelSize: 8
                                font.bold: true
                            }
                        }
                    }

                    // 8-Bar Reactive Waveform (Reacts to chatbot response audio)
                    Row {
                        spacing: 3
                        anchors.horizontalCenter: parent.horizontalCenter
                        height: 24

                        Repeater {
                            model: [
                                { "color": "#6366f1", "maxH": 16, "dur": 240 },
                                { "color": "#8b5cf6", "maxH": 22, "dur": 190 },
                                { "color": "#a855f7", "maxH": 26, "dur": 270 },
                                { "color": "#c084fc", "maxH": 24, "dur": 210 },
                                { "color": "#d946ef", "maxH": 26, "dur": 260 },
                                { "color": "#ec4899", "maxH": 20, "dur": 220 },
                                { "color": "#8b5cf6", "maxH": 18, "dur": 280 },
                                { "color": "#6366f1", "maxH": 14, "dur": 230 }
                            ]
                            Rectangle {
                                width: 3
                                radius: 2
                                color: modelData.color
                                anchors.verticalCenter: parent.verticalCenter
                                height: root.busy ? Math.max(6, modelData.maxH * Math.max(0.4, root.assistantAudioLevel)) : 3

                                Behavior on height {
                                    NumberAnimation { duration: 80 }
                                }

                                SequentialAnimation on height {
                                    running: root.busy
                                    loops: Animation.Infinite
                                    NumberAnimation { to: Math.max(8, modelData.maxH * Math.max(0.45, root.assistantAudioLevel)); duration: modelData.dur }
                                    NumberAnimation { to: 4; duration: modelData.dur }
                                }
                            }
                        }
                    }
                }
            }
        }

        // Auto-lock on exit caption
        Text {
            x: 10
            y: 408
            width: 180
            horizontalAlignment: Text.AlignHCenter
            text: "Auto-lock on exit (10s)"
            color: "#64748b" // Preview: text-slate-600
            font.pixelSize: 8
        }

        // Exit Session Touch Button
        Button {
            id: exitSessionBtn
            x: 10
            y: 424
            width: 180
            height: 42
            text: "✕ Exit Session"
            onClicked: root.closeRequested()

            background: Rectangle {
                radius: 8
                color: exitSessionBtn.down ? "#be123c" : (exitSessionBtn.hovered ? "#e11d48" : "#f43f5e") // Preview: bg-rose-500
                border.width: 1
                border.color: "#fda4af"
            }

            contentItem: RowLayout {
                anchors.centerIn: parent
                spacing: 6
                Text {
                    text: exitSessionBtn.text
                    color: "#ffffff"
                    font.pixelSize: 12
                    font.bold: true
                }
            }
        }
    }

    // ==========================================
    // 2. VERTICAL GRADIENT STRIPE (3px width at x: 200)
    // ==========================================
    Rectangle {
        id: gradientDivider
        x: 200
        y: 0
        width: 3
        height: root.height
        z: 25

        gradient: Gradient {
            GradientStop { position: 0.0; color: "#2dd4bf" } // Preview: teal-400
            GradientStop { position: 0.5; color: "#6366f1" } // Preview: indigo-500
            GradientStop { position: 1.0; color: "#a855f7" } // Preview: purple-500
        }
    }

    // ==========================================
    // 3. RIGHT CONVERSATION PANEL (75% / 597px width)
    // ==========================================
    Rectangle {
        id: rightPanel
        x: 203
        y: 0
        width: root.width - 203
        height: root.height
        color: "#f8fafc" // Preview: bg-slate-50

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            // Slim Top Header (34px) with Brand Gradients
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 34
                color: "#ffffff"
                border.width: 1
                border.color: "#e2e8f0" // Preview: border-slate-200
                z: 10

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    spacing: 8

                    // AI Logo Badge
                    Rectangle {
                        width: 20
                        height: 20
                        radius: 5
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0.0; color: "#06b6d4" }
                            GradientStop { position: 1.0; color: "#4f46e5" }
                        }

                        Text {
                            anchors.centerIn: parent
                            text: "AI"
                            color: "#ffffff"
                            font.pixelSize: 10
                            font.bold: true
                        }
                    }

                    Text {
                        text: "Campus Voice Assistant"
                        color: "#1e293b" // Preview: text-slate-800
                        font.pixelSize: 12
                        font.bold: true
                    }

                    Rectangle {
                        radius: 3
                        color: "#eef2ff" // Preview: bg-indigo-50
                        border.width: 1
                        border.color: "#c7d2fe" // Preview: border-indigo-200
                        implicitWidth: liveTag.implicitWidth + 8
                        implicitHeight: 18

                        Text {
                            id: liveTag
                            anchors.centerIn: parent
                            text: "Gemini 2.5 Live"
                            color: "#4338ca" // Preview: text-indigo-700
                            font.pixelSize: 9
                            font.bold: true
                        }
                    }

                    Item { Layout.fillWidth: true }

                    // Status: Edge Audio Connected
                    Row {
                        spacing: 5
                        Rectangle {
                            width: 6
                            height: 6
                            radius: 3
                            color: "#10b981" // emerald-500
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: "Edge Audio Connected"
                            color: "#64748b" // slate-500
                            font.pixelSize: 10
                            font.bold: true
                        }
                    }

                    // Interrupt Button (only visible while assistant is answering)
                    Button {
                        id: interruptBtn
                        visible: root.busy
                        implicitWidth: 78
                        implicitHeight: 26
                        text: "■ Interrupt"
                        onClicked: root.stopAnsweringRequested()
                        background: Rectangle {
                            radius: 4
                            color: interruptBtn.down ? "#991b1b" : "#ef4444"
                        }
                        contentItem: Text {
                            text: interruptBtn.text
                            color: "#ffffff"
                            font.pixelSize: 10
                            font.bold: true
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }

                    // Mic Mute / Unmute Toggle Button
                    Button {
                        id: muteBtn
                        implicitWidth: 68
                        implicitHeight: 26
                        text: root.muted ? "🔇 Unmute" : "🎙️ Mute"
                        onClicked: root.toggleMuteRequested()
                        background: Rectangle {
                            radius: 4
                            color: root.muted ? "#fee2e2" : "#f1f5f9"
                            border.width: 1
                            border.color: root.muted ? "#f87171" : "#cbd5e1"
                        }
                        contentItem: Text {
                            text: muteBtn.text
                            color: root.muted ? "#dc2626" : "#334155"
                            font.pixelSize: 10
                            font.bold: true
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }
            }

            // Message History Area (fills expansive viewport)
            ListView {
                id: history
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.margins: 12
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                spacing: 12
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
                        width: Math.min(parent.width * 0.86, 500)
                        x: modelData.role === "user" ? parent.width - width : 0
                        implicitHeight: messageColumn.implicitHeight + 16
                        height: implicitHeight
                        radius: 12

                        // User: Vibrant Royal Blue to Indigo Gradient (matches preview)
                        // Assistant: Elevated White Card with border (matches preview)
                        gradient: modelData.role === "user" ? userGrad : null
                        color: modelData.role === "user" ? "transparent" : (modelData.role === "system" ? "#f1f5f9" : "#ffffff")
                        border.width: modelData.role === "user" ? 0 : 1
                        border.color: modelData.role === "system" ? "#e2e8f0" : "#e2e8f0"

                        Gradient {
                            id: userGrad
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0.0; color: "#2563eb" } // blue-600
                            GradientStop { position: 1.0; color: "#4f46e5" } // indigo-600
                        }

                        Column {
                            id: messageColumn
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 10
                            spacing: 4

                            // Header inside bubble
                            RowLayout {
                                width: parent.width
                                spacing: 4

                                Text {
                                    visible: modelData.role === "user"
                                    text: "🎙️ You asked:"
                                    color: "#dbeafe" // blue-100
                                    font.pixelSize: 9
                                    font.bold: true
                                }

                                Row {
                                    visible: modelData.role !== "user" && modelData.role !== "system"
                                    spacing: 4
                                    Rectangle {
                                        width: 7
                                        height: 7
                                        radius: 4
                                        gradient: Gradient {
                                            orientation: Gradient.Horizontal
                                            GradientStop { position: 0.0; color: "#06b6d4" }
                                            GradientStop { position: 1.0; color: "#6366f1" }
                                        }
                                        anchors.verticalCenter: parent.verticalCenter
                                    }
                                    Text {
                                        text: "Assistant"
                                        color: "#4f46e5" // indigo-600
                                        font.pixelSize: 9
                                        font.bold: true
                                    }
                                }
                            }

                            // Message Body
                            Text {
                                width: parent.width
                                text: String(modelData.content || "").replace(/\n/g, "\n\n")
                                color: modelData.role === "user" ? "#ffffff" : (modelData.role === "system" ? "#334155" : "#1e293b")
                                font.pixelSize: 12
                                textFormat: Text.MarkdownText
                                wrapMode: Text.WordWrap
                            }

                            // Verified Source Citation Badge
                            Rectangle {
                                visible: modelData.citations && modelData.citations.length > 0 && modelData.role !== "user"
                                radius: 3
                                color: "#eff6ff" // bg-blue-50
                                border.width: 1
                                border.color: "#bfdbfe" // border-blue-200
                                implicitWidth: citeText.implicitWidth + 10
                                implicitHeight: 18

                                Text {
                                    id: citeText
                                    anchors.centerIn: parent
                                    text: "📄 " + root.citationText(modelData.citations) + " [VERIFIED]"
                                    color: "#1d4ed8" // text-blue-700
                                    font.pixelSize: 8
                                    font.bold: true
                                }
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
                Layout.margins: 8
                height: 26
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
                        font.pixelSize: 11
                    }
                    Text {
                        text: root.ragStatus
                        color: "#0369a1"
                        font.pixelSize: 11
                        font.bold: true
                    }
                }
            }

            // Campus Navigation Card (Matches Preview turn-by-turn route)
            Rectangle {
                id: navCard
                Layout.fillWidth: true
                Layout.margins: 10
                radius: 8
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: "#f8fafc" }
                    GradientStop { position: 1.0; color: "#eef2ff" }
                }
                border.width: 1
                border.color: "#cbd5e1"
                visible: root.currentNavigation !== null && root.currentNavigation !== undefined && Object.keys(root.currentNavigation).length > 0
                implicitHeight: navCol.implicitHeight + 16

                // Indigo left border strip (border-l-4 border-indigo-600)
                Rectangle {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: 4
                    radius: 2
                    color: "#4f46e5"
                }

                ColumnLayout {
                    id: navCol
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 8
                    anchors.topMargin: 8
                    anchors.bottomMargin: 8
                    spacing: 4

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        Rectangle {
                            width: 18
                            height: 18
                            radius: 9
                            color: "#f59e0b" // amber-500
                            Text {
                                anchors.centerIn: parent
                                text: "📍"
                                font.pixelSize: 10
                            }
                        }

                        Text {
                            text: {
                                var sum = root.currentNavigation ? (root.currentNavigation.route_summary || {}) : {}
                                var target = root.currentNavigation ? (root.currentNavigation.navigation_target || {}) : {}
                                var dest = target.label || sum.destination_label || "Destination"
                                return "Destination: " + dest
                            }
                            font.pixelSize: 11
                            font.bold: true
                            color: "#3730a3" // text-indigo-800
                        }

                        Item { Layout.fillWidth: true }

                        Rectangle {
                            radius: 3
                            color: "#e0e7ff"
                            implicitWidth: floorPillText.implicitWidth + 8
                            implicitHeight: 16

                            Text {
                                id: floorPillText
                                anchors.centerIn: parent
                                text: {
                                    var sum = root.currentNavigation ? (root.currentNavigation.route_summary || {}) : {}
                                    var dist = sum.total_distance_m ? (sum.total_distance_m + " m") : ""
                                    var timeLabel = sum.estimated_time_label || ""
                                    return dist ? (dist + " • " + timeLabel) : "Campus Route"
                                }
                                font.pixelSize: 9
                                font.bold: true
                                color: "#3730a3"
                            }
                        }
                    }

                    Column {
                        Layout.fillWidth: true
                        spacing: 3
                        Repeater {
                            model: (root.currentNavigation && root.currentNavigation.instructions) ? root.currentNavigation.instructions : []
                            RowLayout {
                                width: parent.width
                                spacing: 6

                                Rectangle {
                                    width: 16
                                    height: 16
                                    radius: 8
                                    color: "#059669" // emerald-600

                                    Text {
                                        anchors.centerIn: parent
                                        text: String(index + 1)
                                        font.pixelSize: 9
                                        font.bold: true
                                        color: "#ffffff"
                                    }
                                }

                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.instruction || ""
                                    font.pixelSize: 11
                                    color: "#334155"
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }
                    }
                }
            }

            // ==========================================
            // Compact Audio Interaction Bar (44px) with Multi-Color Sound Waves
            // (Matches Preview footer exactly!)
            // ==========================================
            Rectangle {
                id: audioFooter
                Layout.fillWidth: true
                Layout.preferredHeight: 44
                color: "#ffffff" // Preview: bg-white
                border.width: 1
                border.color: "#e2e8f0" // Preview: border-slate-200

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    spacing: 8

                    // Left: Glowing Gradient Mic Button
                    Row {
                        spacing: 8
                        Layout.alignment: Qt.AlignVCenter

                        Rectangle {
                            id: compactMicBtn
                            width: 32
                            height: 32
                            radius: 16
                            gradient: Gradient {
                                orientation: Gradient.Horizontal
                                GradientStop { position: 0.0; color: root.muted ? "#94a3b8" : "#06b6d4" }
                                GradientStop { position: 1.0; color: root.muted ? "#64748b" : "#4f46e5" }
                            }

                            Text {
                                anchors.centerIn: parent
                                text: root.muted ? "🔇" : "🎙️"
                                font.pixelSize: 14
                            }

                            MouseArea {
                                anchors.fill: parent
                                onClicked: root.toggleMuteRequested()
                            }
                        }

                        Row {
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 5

                            Rectangle {
                                width: 7
                                height: 7
                                radius: 4
                                color: root.muted ? "#ef4444" : (root.busy ? "#a855f7" : (root.speaking ? "#10b981" : "#06b6d4"))
                                anchors.verticalCenter: parent.verticalCenter

                                SequentialAnimation on opacity {
                                    loops: Animation.Infinite
                                    NumberAnimation { to: 0.3; duration: 500 }
                                    NumberAnimation { to: 1.0; duration: 500 }
                                }
                            }

                            Text {
                                text: root.muted
                                      ? "Mic Muted"
                                      : (root.busy
                                         ? "Assistant speaking..."
                                         : (root.speaking
                                            ? "Listening to you..."
                                            : "Listening..."))
                                color: root.muted
                                       ? "#991b1b"
                                       : (root.busy
                                          ? "#4338ca"
                                          : (root.speaking
                                             ? "#1e3a8a"
                                             : "#312e81"))
                                font.pixelSize: 11
                                font.bold: true
                            }
                        }
                    }

                    Item { Layout.fillWidth: true }

                    // Center: Dual Multi-Colored Sound Wave Indicators
                    // (Left group: User voice cyan-blue; Right group: AI voice indigo-purple)
                    Row {
                        Layout.alignment: Qt.AlignVCenter
                        spacing: 3

                        // Group 1: You (Live Voice)
                        Repeater {
                            model: [
                                { "color": "#06b6d4", "maxH": 18 },
                                { "color": "#0ea5e9", "maxH": 24 },
                                { "color": "#3b82f6", "maxH": 22 },
                                { "color": "#4f46e5", "maxH": 16 }
                            ]
                            Rectangle {
                                width: 2
                                radius: 1
                                color: modelData.color
                                anchors.verticalCenter: parent.verticalCenter
                                height: root.speaking ? Math.max(4, modelData.maxH * Math.max(0.3, root.userAudioLevel)) : (root.listening && !root.muted ? 4 : 2)

                                Behavior on height { NumberAnimation { duration: 70 } }

                                SequentialAnimation on height {
                                    running: root.speaking
                                    loops: Animation.Infinite
                                    NumberAnimation { to: Math.max(6, modelData.maxH * Math.max(0.4, root.userAudioLevel)); duration: 250 }
                                    NumberAnimation { to: 3; duration: 250 }
                                }
                            }
                        }

                        // Dot separator
                        Rectangle {
                            width: 2
                            height: 2
                            radius: 1
                            color: "#cbd5e1"
                            anchors.verticalCenter: parent.verticalCenter
                        }

                        // Group 2: Campus AI (Voice Response)
                        Repeater {
                            model: [
                                { "color": "#6366f1", "maxH": 16 },
                                { "color": "#8b5cf6", "maxH": 24 },
                                { "color": "#a855f7", "maxH": 22 },
                                { "color": "#ec4899", "maxH": 18 }
                            ]
                            Rectangle {
                                width: 2
                                radius: 1
                                color: modelData.color
                                anchors.verticalCenter: parent.verticalCenter
                                height: root.busy ? Math.max(4, modelData.maxH * Math.max(0.35, root.assistantAudioLevel)) : 2

                                Behavior on height { NumberAnimation { duration: 70 } }

                                SequentialAnimation on height {
                                    running: root.busy
                                    loops: Animation.Infinite
                                    NumberAnimation { to: Math.max(6, modelData.maxH * Math.max(0.45, root.assistantAudioLevel)); duration: 240 }
                                    NumberAnimation { to: 3; duration: 240 }
                                }
                            }
                        }
                    }

                    Item { Layout.fillWidth: true }

                    // Right: Audio Guidance
                    Text {
                        text: "Speak naturally to query or interrupt"
                        color: "#64748b" // slate-500
                        font.pixelSize: 10
                        font.weight: Font.Medium
                    }
                }
            }
        }
    }

    function citationText(citations) {
        if (!citations || citations.length === 0) {
            return "Campus Handbook"
        }
        var labels = []
        for (var i = 0; i < Math.min(citations.length, 2); i++) {
            var citation = citations[i]
            labels.push(citation.document_title || citation.title || citation.chunk_id || ("Doc " + (i + 1)))
        }
        return labels.join(", ")
    }
}
