import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: root
    width: 1280
    height: 720
    visible: true
    visibility: Window.FullScreen
    color: "#020617"
    title: "Edge Access Control"

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
        messages: accessController.messages
        sessionName: accessController.sessionName
        presenceState: accessController.presenceState
        listening: chatbotController.listening
        busy: chatbotController.busy
        muted: chatbotController.muted
        errorText: accessController.chatError
        verifying: accessController.chatVerificationActive
        onCloseRequested: accessController.exitChat()
        onMessageRequested: function(message) { accessController.sendMessage(message) }
        onToggleMuteRequested: accessController.toggleMute()
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
        onClicked: accessController.openChat()
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
        onRefreshRequested: deviceController.refresh()
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
        border.width: accessController.mode === "access-granted" || accessController.mode === "access-denied" ? 12 : 0
        border.color: accessController.mode === "access-granted" ? "#22c55e" : "#ef4444"

        Behavior on border.width { NumberAnimation { duration: 140 } }
    }

    Repeater {
        model: 3
        Rectangle {
            anchors.fill: parent
            z: 109 - index
            color: "transparent"
            border.width: accessController.mode === "access-granted" || accessController.mode === "access-denied" ? 18 + index * 18 : 0
            border.color: accessController.mode === "access-granted" ? "#22c55e" : "#ef4444"
            opacity: accessController.mode === "access-granted" || accessController.mode === "access-denied" ? 0.18 / (index + 1) : 0

            SequentialAnimation on opacity {
                running: accessController.mode === "access-granted" || accessController.mode === "access-denied"
                loops: Animation.Infinite
                NumberAnimation { to: 0.06; duration: 520 }
                NumberAnimation { to: 0.18 / (index + 1); duration: 520 }
            }
        }
    }
}
