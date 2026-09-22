import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    width: 800
    height: 480
    clip: true

    property var messages: []
    property string partialText: ""
    property string transcribedText: ""
    property string sessionName: "Visitor"
    property string presenceState: "UNKNOWN"
    readonly property bool ownerPresent: presenceState === "OWNER_PRESENT"
    property bool listening: false
    property bool busy: false
    property bool speaking: false
    property bool assistantSpeaking: false
    property real userAudioLevel: 0.0
    property real assistantAudioLevel: 0.0
    property string ragStatus: ""
    property var currentNavigation: null
    property var citations: []
    property bool muted: false
    property bool verifying: false
    property string errorText: ""

    function isUserTextCommitted(text) {
        if (!text || !messages || messages.length === 0) return false
        var trimmed = text.trim()
        if (!trimmed) return false
        for (var i = messages.length - 1; i >= Math.max(0, messages.length - 2); i--) {
            if (messages[i].role === "user" && String(messages[i].content || "").trim() === trimmed) {
                return true
            }
        }
        return false
    }

    function isAssistantTextCommitted(text) {
        if (!text || !messages || messages.length === 0) return false
        var trimmed = text.trim()
        if (!trimmed) return false
        var last = messages[messages.length - 1]
        return Boolean(last && last.role === "assistant" && String(last.content || "").trim() === trimmed)
    }

    readonly property bool hasAssistantMessageInFlight: {
        if (partialText && partialText.trim().length > 0) return true
        if (!messages || messages.length === 0) return false
        var last = messages[messages.length - 1]
        return last && last.role === "assistant"
    }

    signal closeRequested()
    signal stopAnsweringRequested()
    signal toggleMuteRequested()
    signal dismissNavigationRequested()

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
        width: Math.min(200, root.width * 0.25)
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
            width: leftDock.width - 20
            height: root.height * 0.24 + 3
            radius: 8
            color: "#020617" // Preview: bg-slate-950
            border.width: 2
            border.color: root.verifying ? "#38bdf8" : (root.ownerPresent ? "#22d3ee" : "#f59e0b")
            Behavior on border.color { ColorAnimation { duration: 250 } }

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
                        text: root.verifying ? "Verifying" : (root.ownerPresent ? "Verified" : "Out of frame")
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
            y: cameraSlot.y + cameraSlot.height + 8
            width: leftDock.width - 20
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
                            color: root.ownerPresent ? "#10b981" : "#f59e0b"
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: root.verifying ? "Verifying" : (root.ownerPresent ? "In Frame" : "Out of Frame")
                            color: root.ownerPresent ? "#059669" : "#d97706" // emerald-600
                            font.pixelSize: 9
                            font.bold: true
                        }
                    }
                }
            }
        }

        // Auto-lock on exit caption
        Text {
            x: 10
            y: root.height - 72
            width: leftDock.width - 20
            horizontalAlignment: Text.AlignHCenter
            text: root.ownerPresent ? "Session closes after 10s away" : "Out of frame — return within 10s"
            wrapMode: Text.Wrap
            color: "#64748b" // Preview: text-slate-600
            font.pixelSize: 8
        }

        // Exit Session Touch Button
        Button {
            id: exitSessionBtn
            x: 10
            y: root.height - 56
            width: leftDock.width - 20
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
        x: leftDock.width
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
        x: gradientDivider.x + gradientDivider.width
        y: 0
        width: root.width - x
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
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        elide: Text.ElideRight
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

                    // Show optional connection text only when the header has room.
                    Row {
                        visible: rightPanel.width >= 720
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
                        visible: root.assistantSpeaking || root.busy || (root.partialText && root.partialText.trim().length > 0)
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
                objectName: "historyListView"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.margins: 12
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                spacing: 12
                model: root.messages || []

                property bool userScrolledUp: false

                function scrollToBottom() {
                    if (!userScrolledUp) {
                        history.positionViewAtEnd()
                    }
                }

                onMovementStarted: userScrolledUp = true
                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                    onPressedChanged: {
                        if (!pressed && (history.atYEnd || history.contentY >= history.contentHeight - history.height - 60)) {
                            history.userScrolledUp = false
                        }
                    }
                }

                onMovementEnded: {
                    if (history.atYEnd || history.contentY >= history.contentHeight - history.height - 60) {
                        userScrolledUp = false
                    } else {
                        userScrolledUp = true
                    }
                }

                onFlickEnded: {
                    if (history.atYEnd || history.contentY >= history.contentHeight - history.height - 60) {
                        userScrolledUp = false
                    } else {
                        userScrolledUp = true
                    }
                }

                onCountChanged: {
                    scrollToBottom()
                }

                onModelChanged: {
                    scrollToBottom()
                }

                onContentHeightChanged: {
                    if (!userScrolledUp && (history.atYEnd || history.contentY >= history.contentHeight - history.height - 60 || history.contentHeight <= history.height)) {
                        scrollToBottom()
                    }
                }

                Component.onCompleted: {
                    scrollToBottom()
                }

                footer: ColumnLayout {
                    width: history.width
                    spacing: 8

                    // In-flight User Message Bubble (voice query while being spoken/processed)
                    Rectangle {
                        id: inFlightUserBubble
                        visible: root.transcribedText.trim().length > 0 && !root.isUserTextCommitted(root.transcribedText)
                        Layout.alignment: Qt.AlignRight
                        width: Math.min(history.width * 0.86, 500)
                        implicitHeight: userInFlightCol.implicitHeight + 20
                        radius: 12
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0.0; color: "#2563eb" } // blue-600
                            GradientStop { position: 1.0; color: "#4f46e5" } // indigo-600
                        }

                        Column {
                            id: userInFlightCol
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 10
                            spacing: 4

                            Text {
                                text: "🎙️ You asked:"
                                color: "#dbeafe" // blue-100
                                font.pixelSize: 9
                                font.bold: true
                            }

                            Text {
                                width: parent.width
                                text: root.transcribedText
                                color: "#ffffff"
                                font.pixelSize: 12
                                wrapMode: Text.Wrap
                            }
                        }
                    }

                    // Inline Organic Assistant Thinking / RAG Indicator
                    Rectangle {
                        id: inlineThinkingBubble
                        visible: (root.ragStatus.length > 0 || (root.busy && root.partialText.trim().length === 0)) && root.partialText.trim().length === 0
                        width: Math.min(history.width * 0.75, 320)
                        implicitHeight: 36
                        radius: 10
                        color: "#f0fdf4" // soft emerald-50
                        border.width: 1
                        border.color: "#86efac" // emerald-300

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            spacing: 8

                            // 3 Animated Bouncing Dots
                            Row {
                                spacing: 4
                                Layout.alignment: Qt.AlignVCenter

                                Repeater {
                                    model: 3
                                    Rectangle {
                                        width: 6
                                        height: 6
                                        radius: 3
                                        color: "#059669" // emerald-600
                                        anchors.verticalCenter: parent.verticalCenter

                                        SequentialAnimation on opacity {
                                            loops: Animation.Infinite
                                            PauseAnimation { duration: index * 160 }
                                            NumberAnimation { to: 0.3; duration: 350; easing.type: Easing.InOutQuad }
                                            NumberAnimation { to: 1.0; duration: 350; easing.type: Easing.InOutQuad }
                                        }

                                        SequentialAnimation on scale {
                                            loops: Animation.Infinite
                                            PauseAnimation { duration: index * 160 }
                                            NumberAnimation { to: 0.7; duration: 350; easing.type: Easing.InOutQuad }
                                            NumberAnimation { to: 1.2; duration: 350; easing.type: Easing.InOutQuad }
                                        }
                                    }
                                }
                            }

                            Text {
                                Layout.fillWidth: true
                                text: root.ragStatus.length > 0 ? "Searching campus database…" : "Thinking…"
                                color: "#065f46" // emerald-800
                                font.pixelSize: 11
                                font.bold: true
                                elide: Text.ElideRight
                            }
                        }
                    }

                    // In-flight Assistant Streaming Bubble
                    Rectangle {
                        id: inFlightAssistantBubble
                        visible: root.partialText.trim().length > 0 && !root.isAssistantTextCommitted(root.partialText)
                        Layout.alignment: Qt.AlignLeft
                        width: Math.min(history.width * 0.86, 500)
                        implicitHeight: botInFlightCol.implicitHeight + 20
                        radius: 12
                        color: "#ffffff"
                        border.width: 1
                        border.color: "#e2e8f0"

                        Column {
                            id: botInFlightCol
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 10
                            spacing: 4

                            Row {
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

                            Text {
                                width: parent.width
                                text: root.displayText({ content: root.partialText, role: "assistant" })
                                color: "#1e293b"
                                font.pixelSize: 12
                                textFormat: Text.MarkdownText
                                wrapMode: Text.Wrap
                            }
                        }
                    }

            // Campus Navigation Card (Light Theme: Multi-Step Directions + Companion QR Code)
            Rectangle {
                id: navCard
                Layout.fillWidth: true
                Layout.margins: 10
                radius: 10
                color: "#ffffff"
                border.width: 1
                border.color: "#cbd5e1"
                visible: root.currentNavigation !== null && root.currentNavigation !== undefined && Object.keys(root.currentNavigation).length > 0
                implicitHeight: navCol.implicitHeight + 20

                // Indigo left border accent strip
                Rectangle {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: 4
                    radius: 2
                    color: "#4f46e5"
                }

                readonly property var qrSession: (root.currentNavigation && root.currentNavigation.qr_session) ? root.currentNavigation.qr_session : null
                readonly property string qrUrl: {
                    if (qrSession) {
                        return qrSession.qr_code_file_url || qrSession.qr_code_local_url || qrSession.qr_code_url || qrSession.qr_code_data_url || ""
                    }
                    if (root.currentNavigation) {
                        return root.currentNavigation.qr_code_file_url || root.currentNavigation.qr_code_local_url || root.currentNavigation.qr_code_url || root.currentNavigation.qr_code_data_url || ""
                    }
                    return ""
                }
                readonly property bool hasQr: qrUrl.length > 0
                readonly property var visualisations: (root.currentNavigation && root.currentNavigation.visualisations) ? root.currentNavigation.visualisations : []
                property int activeFloorIndex: 0
                readonly property string routeMapUrl: {
                    if (visualisations.length > 0) {
                        var idx = Math.min(Math.max(0, activeFloorIndex), visualisations.length - 1)
                        var v = visualisations[idx]
                        return v.file_url || v.local_image_url || v.image_url || ""
                    }
                    return ""
                }
                property bool showMapGuide: false

                ColumnLayout {
                    id: navCol
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.leftMargin: 14
                    anchors.rightMargin: 10
                    anchors.topMargin: 10
                    spacing: 8

                    // Header Row: Destination, Distance/ETA Pill, and Dismiss Button
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        Rectangle {
                            width: 20
                            height: 20
                            radius: 10
                            color: "#fef3c7"
                            border.width: 1
                            border.color: "#fde68a"
                            Text {
                                anchors.centerIn: parent
                                text: "📍"
                                font.pixelSize: 11
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            text: {
                                var sum = root.currentNavigation ? (root.currentNavigation.route_summary || {}) : {}
                                var target = root.currentNavigation ? (root.currentNavigation.navigation_target || {}) : {}
                                var dest = target.label || sum.destination_label || "Destination"
                                return "Destination: " + dest
                            }
                            font.pixelSize: 12
                            font.bold: true
                            color: "#0f172a"
                        }

                        Rectangle {
                            radius: 4
                            color: "#e0e7ff"
                            border.width: 1
                            border.color: "#c7d2fe"
                            implicitWidth: floorPillText.implicitWidth + 10
                            implicitHeight: 20

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

                        // Dismiss Navigation Button
                        Rectangle {
                            id: dismissNavBtn
                            width: 20
                            height: 20
                            radius: 10
                            color: dismissNavMouse.pressed ? "#cbd5e1" : (dismissNavMouse.containsMouse ? "#e2e8f0" : "#f1f5f9")
                            border.width: 1
                            border.color: "#cbd5e1"

                            Text {
                                anchors.centerIn: parent
                                text: "✕"
                                font.pixelSize: 10
                                font.bold: true
                                color: "#64748b"
                            }

                            MouseArea {
                                id: dismissNavMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    root.currentNavigation = null
                                    root.dismissNavigationRequested()
                                }
                            }
                        }
                    }

                    // Content Row: Left = Multi-Step Directions, Right = QR Code Card
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        Layout.alignment: Qt.AlignTop

                        // Left Section: Multi-Step Turn-by-Turn List or Map Image
                        Rectangle {
                            Layout.fillWidth: true
                            height: 160
                            Layout.preferredHeight: 160
                            radius: 8
                            color: "#f8fafc"
                            border.width: 1
                            border.color: "#e2e8f0"
                            clip: true

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 6
                                spacing: 4

                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: navCard.showMapGuide ? "🗺️ Floor Plan Map" : "🚶 Directions on Kiosk"
                                        font.pixelSize: 9
                                        font.bold: true
                                        color: navCard.showMapGuide ? "#4f46e5" : "#059669"
                                    }
                                    Item { Layout.fillWidth: true }
                                    
                                    // View Toggle: Steps vs Map
                                    Row {
                                        spacing: 3
                                        visible: navCard.routeMapUrl.length > 0
                                        Rectangle {
                                            radius: 3
                                            color: !navCard.showMapGuide ? "#059669" : "#ffffff"
                                            border.width: 1
                                            border.color: !navCard.showMapGuide ? "#059669" : "#cbd5e1"
                                            implicitWidth: 38
                                            implicitHeight: 16
                                            Text {
                                                anchors.centerIn: parent
                                                text: "Steps"
                                                font.pixelSize: 8
                                                font.bold: true
                                                color: !navCard.showMapGuide ? "#ffffff" : "#64748b"
                                            }
                                            MouseArea {
                                                anchors.fill: parent
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: navCard.showMapGuide = false
                                            }
                                        }
                                        Rectangle {
                                            radius: 3
                                            color: navCard.showMapGuide ? "#4f46e5" : "#ffffff"
                                            border.width: 1
                                            border.color: navCard.showMapGuide ? "#4f46e5" : "#cbd5e1"
                                            implicitWidth: 34
                                            implicitHeight: 16
                                            Text {
                                                anchors.centerIn: parent
                                                text: "Map"
                                                font.pixelSize: 8
                                                font.bold: true
                                                color: navCard.showMapGuide ? "#ffffff" : "#64748b"
                                            }
                                            MouseArea {
                                                anchors.fill: parent
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: navCard.showMapGuide = true
                                            }
                                        }
                                    }

                                    // Floor Level Switcher for Kiosk Map (Ordered: 1. Start -> 2. Next -> 3. Destination)
                                    Row {
                                        spacing: 2
                                        visible: navCard.showMapGuide && navCard.visualisations.length > 1
                                        Repeater {
                                            model: navCard.visualisations
                                            Rectangle {
                                                radius: 3
                                                color: navCard.activeFloorIndex === index ? "#4f46e5" : "#ffffff"
                                                border.width: 1
                                                border.color: navCard.activeFloorIndex === index ? "#4f46e5" : "#cbd5e1"
                                                implicitWidth: floorBtnText.implicitWidth + 8
                                                implicitHeight: 16
                                                Text {
                                                    id: floorBtnText
                                                    anchors.centerIn: parent
                                                    text: {
                                                        var item = modelData || {}
                                                        var bld = item.building_name || "L"
                                                        var lvl = item.floor_level != null ? item.floor_level : (index + 1)
                                                        var prefix = index === 0 ? "1." : (index + 1) + "."
                                                        return prefix + bld + " F" + lvl
                                                    }
                                                    font.pixelSize: 8
                                                    font.bold: true
                                                    color: navCard.activeFloorIndex === index ? "#ffffff" : "#475569"
                                                }
                                                MouseArea {
                                                    anchors.fill: parent
                                                    cursorShape: Qt.PointingHandCursor
                                                    onClicked: navCard.activeFloorIndex = index
                                                }
                                            }
                                        }
                                    }

                                    Rectangle {
                                        visible: !navCard.showMapGuide && navCard.routeMapUrl.length === 0
                                        radius: 3
                                        color: "#ffffff"
                                        border.width: 1
                                        border.color: "#e2e8f0"
                                        implicitWidth: stepCountText.implicitWidth + 8
                                        implicitHeight: 16
                                        Text {
                                            id: stepCountText
                                            anchors.centerIn: parent
                                            text: {
                                                var count = (root.currentNavigation && root.currentNavigation.instructions) ? root.currentNavigation.instructions.length : 0
                                                return count + (count === 1 ? " Step" : " Steps")
                                            }
                                            font.pixelSize: 8
                                            font.bold: true
                                            color: "#64748b"
                                        }
                                    }
                                }

                                // 1. Map Image View
                                Item {
                                    visible: navCard.showMapGuide && navCard.routeMapUrl.length > 0
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true

                                    Image {
                                        anchors.fill: parent
                                        anchors.margins: 2
                                        source: navCard.routeMapUrl
                                        fillMode: Image.PreserveAspectFit
                                        smooth: true
                                        asynchronous: false
                                        onStatusChanged: {
                                            if (status === Image.Error) {
                                                console.warn("[ChatbotView] Map image failed to load from:", source)
                                            } else if (status === Image.Ready) {
                                                console.log("[ChatbotView] Map image loaded successfully from:", source)
                                            }
                                        }
                                    }
                                }

                                // 2. Turn-by-Turn Steps View
                                Flickable {
                                    visible: !navCard.showMapGuide || navCard.routeMapUrl.length === 0
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    contentHeight: stepsRepeaterCol.implicitHeight
                                    clip: true
                                    boundsBehavior: Flickable.StopAtBounds
                                    ScrollBar.vertical: ScrollBar {
                                        policy: ScrollBar.AsNeeded
                                        width: 4
                                    }

                                    Column {
                                        id: stepsRepeaterCol
                                        width: parent.width - 6
                                        spacing: 4

                                        Repeater {
                                            model: (root.currentNavigation && root.currentNavigation.instructions) ? root.currentNavigation.instructions : []
                                            Rectangle {
                                                width: parent.width
                                                radius: 6
                                                color: "#ffffff"
                                                border.width: 1
                                                border.color: "#e2e8f0"
                                                implicitHeight: stepRow.implicitHeight + 8

                                                RowLayout {
                                                    id: stepRow
                                                    anchors.fill: parent
                                                    anchors.margins: 4
                                                    spacing: 6

                                                    Rectangle {
                                                        width: 18
                                                        height: 18
                                                        radius: 9
                                                        color: index === 0 ? "#059669" : (index === ((root.currentNavigation.instructions.length) - 1) ? "#d97706" : "#4f46e5")

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
                                                        text: modelData.instruction || modelData.description || ""
                                                        font.pixelSize: 10
                                                        color: "#1e293b"
                                                        wrapMode: Text.Wrap
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        // Right Section: Scannable QR Code Card (Light Theme)
                        Rectangle {
                            visible: navCard.hasQr
                            Layout.preferredWidth: 140
                            Layout.preferredHeight: 160
                            height: 160
                            radius: 8
                            color: "#ffffff"
                            border.width: 1
                            border.color: "#e2e8f0"

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 6
                                spacing: 2
                                Layout.alignment: Qt.AlignHCenter

                                Rectangle {
                                    Layout.alignment: Qt.AlignHCenter
                                    width: 84
                                    height: 84
                                    radius: 6
                                    color: "#ffffff"
                                    border.width: 1
                                    border.color: "#cbd5e1"

                                    Image {
                                        anchors.fill: parent
                                        anchors.margins: 3
                                        source: navCard.qrUrl
                                        fillMode: Image.PreserveAspectFit
                                        smooth: true
                                        asynchronous: false
                                        onStatusChanged: {
                                            if (status === Image.Error) {
                                                console.warn("[ChatbotView] QR code failed to load from:", source)
                                            } else if (status === Image.Ready) {
                                                console.log("[ChatbotView] QR code loaded successfully from:", source)
                                            }
                                        }
                                    }
                                }

                                Text {
                                    Layout.alignment: Qt.AlignHCenter
                                    text: "📱 Mobile Map"
                                    font.pixelSize: 10
                                    font.bold: true
                                    color: "#0f172a"
                                }

                                Text {
                                    Layout.fillWidth: true
                                    horizontalAlignment: Text.AlignHCenter
                                    text: "Scan to open on phone"
                                    font.pixelSize: 8
                                    color: "#64748b"
                                    wrapMode: Text.Wrap
                                }

                                Rectangle {
                                    Layout.alignment: Qt.AlignHCenter
                                    radius: 3
                                    color: "#e0e7ff"
                                    implicitWidth: expText.implicitWidth + 8
                                    implicitHeight: 15
                                    Text {
                                        id: expText
                                        anchors.centerIn: parent
                                        text: {
                                            var min = navCard.qrSession ? (navCard.qrSession.expires_in_minutes || 15) : 15
                                            return "⏱️ " + min + "m session"
                                        }
                                        font.pixelSize: 7
                                        font.bold: true
                                        color: "#3730a3"
                                    }
                                }
                            }
                        }
                    }
                }
            }

                }

                delegate: Item {
                    width: history.width
                    height: Math.max(1, bubble.implicitHeight)

                    Rectangle {
                        id: bubble
                        width: Math.min(parent.width * 0.86, 500)
                        x: modelData.role === "user" ? parent.width - width : 0
                        implicitHeight: messageColumn.implicitHeight + 20
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
                                text: root.displayText(modelData)
                                color: modelData.role === "user" ? "#ffffff" : (modelData.role === "system" ? "#334155" : "#1e293b")
                                font.pixelSize: 12
                                textFormat: Text.MarkdownText
                                wrapMode: Text.Wrap
                            }


                        }
                    }
                }
            }

            // Error display if present (suppress 404/Not Found technical codes)
            Text {
                Layout.fillWidth: true
                text: root.errorText
                visible: root.errorText.length > 0 && root.errorText !== "Not Found" && !root.errorText.includes("404")
                color: "#dc2626"
                font.pixelSize: 11
                elide: Text.ElideRight
                horizontalAlignment: Text.AlignHCenter
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
                                color: root.muted ? "#ef4444" : (root.assistantSpeaking ? "#10b981" : (root.ragStatus.length > 0 || root.busy ? "#a855f7" : (root.speaking ? "#06b6d4" : "#3b82f6")))
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
                                      : (root.assistantSpeaking
                                         ? "Assistant speaking..."
                                         : (root.ragStatus.length > 0
                                            ? "Searching database..."
                                            : (root.busy
                                               ? "Thinking..."
                                               : (root.speaking ? "Listening to you..." : "Listening..."))))
                                color: root.muted
                                       ? "#991b1b"
                                       : (root.assistantSpeaking
                                          ? "#1e3a8a"
                                          : (root.busy || root.ragStatus.length > 0
                                             ? "#4338ca"
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
                                height: (root.assistantSpeaking || root.busy) ? Math.max(4, modelData.maxH * Math.max(0.35, root.assistantAudioLevel)) : 2

                                Behavior on height { NumberAnimation { duration: 70 } }

                                SequentialAnimation on height {
                                    running: root.assistantSpeaking || root.busy
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
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        elide: Text.ElideRight
                        text: "Speak naturally to query or interrupt"
                        color: "#64748b" // slate-500
                        font.pixelSize: 10
                        font.weight: Font.Medium
                    }
                }
            }
        }

        // Floating "Jump to Latest" Button (appears when user manually scrolls up)
        Rectangle {
            id: jumpToBottomBtn
            anchors.bottom: parent.bottom
            anchors.right: parent.right
            anchors.bottomMargin: 54
            anchors.rightMargin: 16
            implicitWidth: jumpRow.implicitWidth + 24
            implicitHeight: 32
            radius: 16
            color: "#ffffff"
            border.width: 1
            border.color: "#c7d2fe" // indigo-200
            visible: history.userScrolledUp && history.contentHeight > history.height
            z: 40

            opacity: visible ? 1.0 : 0.0
            Behavior on opacity { NumberAnimation { duration: 150 } }

            Row {
                id: jumpRow
                anchors.centerIn: parent
                spacing: 6

                Text {
                    text: "↓"
                    color: "#4f46e5"
                    font.pixelSize: 12
                    font.bold: true
                }

                Text {
                    text: "Jump to latest"
                    color: "#3730a3"
                    font.pixelSize: 11
                    font.bold: true
                }
            }

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    history.userScrolledUp = false
                    history.scrollToBottom()
                }
            }
        }
    }

    function displayText(message) {
        var text = String(message.content || "")
        if (message.role === "user") return text
        return text.replace(/\[(?:\d+(?:[,–-]\s*\d+)*|(?:source|doc)\s*\d+)\]/gi, "")
                   .replace(/【[^】]*】/g, "")
                   .replace(/\[Sources?:[^\]]*\]/gi, "")
    }
}
