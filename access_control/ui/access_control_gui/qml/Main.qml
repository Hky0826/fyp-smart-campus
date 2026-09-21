import QtQuick
import QtQuick.Controls

ApplicationWindow {
    id: root
    width: 800
    height: 480
    visible: true
    visibility: Window.FullScreen
    flags: Qt.Window | Qt.FramelessWindowHint
    color: "#020617"
    title: "Edge Access Control"
    readonly property bool showAccessGlow: !accessController.chatExpanded
                                           && (accessController.mode === "access-granted"
                                               || accessController.mode === "access-denied")

    CameraView {
        id: cameraView
        minimized: accessController.chatCameraMinimized
        sourceUrl: cameraController.sourceUrl
        videoWidth: cameraController.videoWidth
        videoHeight: cameraController.videoHeight
        boxes: accessController.faceBoxes
    }

    ChatbotView {
        id: chatbotView
        anchors.fill: parent
        z: 20
        visible: accessController.chatExpanded
        messages: accessController.committedMessages
        partialText: chatbotController.partialText
        transcribedText: chatbotController.transcribedText
        sessionName: accessController.sessionName
        presenceState: accessController.presenceState
        listening: chatbotController.listening
        busy: chatbotController.busy
        speaking: chatbotController.speaking
        assistantSpeaking: chatbotController.assistantSpeaking
        ragStatus: chatbotController.ragStatus
        currentNavigation: chatbotController.currentNavigation
        citations: chatbotController.citations
        muted: chatbotController.muted
        errorText: accessController.chatError
        verifying: accessController.chatVerificationActive
        userAudioLevel: chatbotController.userAudioLevel
        assistantAudioLevel: chatbotController.assistantAudioLevel
        onCloseRequested: accessController.exitChat()
        onStopAnsweringRequested: chatbotController.stopAudioPlayback()
        onToggleMuteRequested: accessController.toggleMute()
        onDismissNavigationRequested: chatbotController.clearNavigation()
    }

    ChatbotButton {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.rightMargin: Math.max(18, parent.width * 0.025)
        anchors.bottomMargin: Math.max(18, parent.width * 0.025)
        z: 62
        visible: !accessController.chatExpanded
        enabled: cameraController.ready && !accessController.offline
        mode: accessController.mode
        dwellProgress: accessController.dwellProgress
        onClicked: accessController.openChat()
    }

    Shortcut {
        sequence: "Esc"
        onActivated: Qt.quit()
    }

    Shortcut {
        sequence: "Ctrl+Q"
        onActivated: Qt.quit()
    }

    Button {
        id: exitAppButton
        text: "✕ Exit"
        z: 120
        visible: !accessController.chatExpanded
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.margins: 14
        height: 36
        font.pixelSize: 13
        font.bold: true
        contentItem: Text {
            text: exitAppButton.text
            font: exitAppButton.font
            color: "#f87171"
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            color: exitAppButton.down ? "#450a0a" : (exitAppButton.hovered ? "#7f1d1d" : "#1e293b")
            border.color: "#ef4444"
            border.width: 1
            radius: 8
            opacity: 0.85
        }
        onClicked: Qt.quit()
    }

    SessionLockedOverlay {
        anchors.fill: parent
        z: 95
        visible: accessController.mode === "chat-locked"
        presenceState: accessController.presenceState
        onEndRequested: accessController.exitChat()
    }

    SetupView {
        anchors.fill: parent
        z: 98
        visible: deviceController.setupRequired && !accessController.offline
        databaseOk: deviceController.databaseOk
        modelsOk: deviceController.modelsOk
        errorText: deviceController.error
        firstTimeSetup: deviceController.firstTimeSetup
        setupDeviceId: deviceController.setupDeviceId
        setupSecret: deviceController.setupSecret
        setupLocalAddress: deviceController.setupLocalAddress
        setupDetectedLanAddress: deviceController.setupDetectedLanAddress
        setupCloudUrl: deviceController.setupCloudUrl
        onRefreshRequested: deviceController.refresh()
        onSetupCompleted: deviceController.completeSetup()
        onProvisionRequested: function(cloudUrl, deviceId, deviceSecret, remotePush) {
            deviceController.applySetup(cloudUrl, deviceId, deviceSecret, remotePush)
        }
    }

    OfflineView {
        anchors.fill: parent
        z: 100
        visible: accessController.offline
        apiBaseUrl: apiBaseUrl
        cameraError: cameraController.error
        onRetryRequested: {
            deviceController.refresh()
            accessController.refreshState()
        }
    }

    Rectangle {
        anchors.fill: parent
        z: 110
        color: "transparent"
        border.width: root.showAccessGlow ? 12 : 0
        border.color: accessController.mode === "access-granted" ? "#22c55e" : "#ef4444"

        Behavior on border.width { NumberAnimation { duration: 140 } }
    }

    Repeater {
        model: 3
        Rectangle {
            anchors.fill: parent
            z: 109 - index
            color: "transparent"
            border.width: root.showAccessGlow ? 18 + index * 18 : 0
            border.color: accessController.mode === "access-granted" ? "#22c55e" : "#ef4444"
            opacity: root.showAccessGlow ? 0.18 / (index + 1) : 0

            SequentialAnimation on opacity {
                running: root.showAccessGlow
                loops: Animation.Infinite
                NumberAnimation { to: 0.06; duration: 520 }
                NumberAnimation { to: 0.18 / (index + 1); duration: 520 }
            }
        }
    }
}
