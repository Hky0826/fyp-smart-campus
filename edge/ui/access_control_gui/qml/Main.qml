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
        anchors.fill: parent
        minimized: accessController.chatCameraMinimized
        sourceUrl: cameraController.sourceUrl
        videoWidth: cameraController.videoWidth
        videoHeight: cameraController.videoHeight
        boxes: accessController.faceBoxes
    }

    ChatbotView {
        id: chatbotView
        anchors.fill: parent
        visible: accessController.chatExpanded
        messages: accessController.messages
        sessionName: accessController.sessionName
        presenceState: accessController.presenceState
        listening: chatbotController.listening
        busy: chatbotController.busy
        errorText: accessController.chatError
        verifying: accessController.chatVerificationActive
        onCloseRequested: accessController.exitChat()
        onMessageRequested: function(message) { accessController.sendMessage(message) }
    }

    AccessOverlay {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.leftMargin: Math.max(18, parent.width * 0.025)
        anchors.bottomMargin: accessController.chatExpanded ? 28 : 104
        z: 60
        titleText: accessController.accessTitle
        subtitleText: accessController.accessSubtitle
        mode: accessController.mode
        cameraError: accessController.cameraError
    }

    ChatbotButton {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.rightMargin: Math.max(18, parent.width * 0.025)
        anchors.bottomMargin: Math.max(18, parent.width * 0.025)
        z: 62
        visible: !accessController.chatExpanded
        enabled: cameraController.ready && !accessController.offline
        onClicked: accessController.openChat()
    }

    AccessResultOverlay {
        anchors.fill: parent
        z: 90
        mode: accessController.mode
        titleText: accessController.accessTitle
        subtitleText: accessController.accessSubtitle
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

    DeviceStatusBar {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        z: 70
        deviceName: accessController.deviceName
        deviceId: accessController.deviceId
        edgeOnline: !accessController.offline
        cloudSync: accessController.cloudSync
        cloudChatbot: accessController.cloudChatbot
    }

    Rectangle {
        anchors.fill: parent
        z: 110
        color: "transparent"
        border.width: accessController.mode === "access-granted" || accessController.mode === "access-denied" ? 10 : 0
        border.color: accessController.mode === "access-granted" ? "#22c55e" : "#ef4444"
    }
}

