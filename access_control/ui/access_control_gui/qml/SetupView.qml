import QtQuick
import QtQuick.Controls

Item {
    id: root
    property bool databaseOk: true
    property bool modelsOk: true
    property bool firstTimeSetup: false
    property string setupDeviceId: ""
    property string setupSecret: ""
    property string setupLocalAddress: ""
    property string setupDetectedLanAddress: ""
    property string setupCloudUrl: ""
    property string cameraSourceUrl: ""
    property string qrStatusText: "Hold the dashboard QR code in front of the camera..."
    property string errorText: ""
    property string cloudUrlValue: setupCloudUrl || "http://127.0.0.1:8000"
    property string pairingCodeValue: ""
    property string deviceIdValue: ""
    property string deviceSecretValue: ""
    property bool remotePushValue: false
    // Default mode is hands-free QR scanning ("qr"); fallbacks: "code" | "manual"
    property string setupMode: "qr"
    signal refreshRequested()
    signal setupCompleted()
    signal scanQrRequested()
    signal claimRequested(string cloudUrl, string pairingCode, bool remotePush)
    signal provisionRequested(string cloudUrl, string deviceId, string deviceSecret, bool remotePush)

    Timer {
        interval: 600
        repeat: true
        running: root.visible && root.firstTimeSetup && root.setupMode === "qr"
        onTriggered: root.scanQrRequested()
    }

    focus: visible
    onVisibleChanged: if (visible) forceActiveFocus()
    onSetupCloudUrlChanged: if (!root.firstTimeSetup && root.setupCloudUrl.length > 0) root.cloudUrlValue = root.setupCloudUrl

    Keys.onPressed: function(event) {
        if (root.visible && !root.firstTimeSetup && !event.isAutoRepeat) {
            root.setupCompleted()
            event.accepted = true
        }
    }

    Rectangle { anchors.fill: parent; color: "#ee020617" }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(720, parent.width - 32)
        height: Math.min(root.firstTimeSetup ? 620 : 280, parent.height - 24)
        radius: 14
        color: "#f8fafc"

        Flickable {
            anchors.fill: parent
            anchors.margins: 22
            contentWidth: width
            contentHeight: setupColumn.height
            clip: true

            Column {
                id: setupColumn
                width: parent.width
                spacing: 12

                Text {
                    width: parent.width
                    text: root.firstTimeSetup ? "Pair this Access-Control Kiosk" : "Device setup required"
                    color: "#0f172a"
                    font.pixelSize: 24
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                }

                // ── DEFAULT MODE: LIVE QR CAMERA SCANNER ──────────────────────
                Column {
                    visible: root.firstTimeSetup && root.setupMode === "qr"
                    width: parent.width
                    spacing: 10

                    Text {
                        width: parent.width
                        text: "In the Admin Dashboard, go to Devices → Add Device (or click the QR icon) and hold the QR code up to this kiosk's camera."
                        color: "#475569"
                        font.pixelSize: 13
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                    }

                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: Math.min(parent.width, 380)
                        height: 230
                        radius: 12
                        color: "#0f172a"
                        border.color: "#06b6d4"
                        border.width: 3
                        clip: true

                        Image {
                            anchors.fill: parent
                            source: root.cameraSourceUrl
                            cache: false
                            fillMode: Image.PreserveAspectCrop
                            mirror: true
                            smooth: true
                        }

                        // Targeting reticle
                        Rectangle {
                            anchors.centerIn: parent
                            width: 150
                            height: 150
                            radius: 12
                            color: "transparent"
                            border.color: "#22d3ee"
                            border.width: 2
                        }

                        Rectangle {
                            anchors.bottom: parent.bottom
                            anchors.left: parent.left
                            anchors.right: parent.right
                            height: 30
                            color: "#aa020617"
                            Text {
                                anchors.centerIn: parent
                                text: root.cameraSourceUrl.length > 0 ? "Scanning for QR code..." : "Starting camera..."
                                color: "#e0f2fe"
                                font.pixelSize: 12
                                font.bold: true
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        text: root.qrStatusText
                        color: "#0369a1"
                        font.pixelSize: 13
                        font.bold: true
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                    }

                    Row {
                        anchors.horizontalCenter: parent.horizontalCenter
                        spacing: 12
                        Button {
                            text: "Type 8-character code instead"
                            onClicked: root.setupMode = "code"
                        }
                        Button {
                            flat: true
                            text: "Manual ID & Secret"
                            onClicked: root.setupMode = "manual"
                        }
                    }
                }

                // ── FALLBACK 1: 8-CHARACTER PAIRING CODE ──────────────────────
                Column {
                    visible: root.firstTimeSetup && root.setupMode === "code"
                    width: parent.width
                    spacing: 10

                    Text { text: "Cloud dashboard URL"; color: "#475569"; font.bold: true; font.pixelSize: 13 }
                    TextField {
                        width: parent.width
                        text: root.cloudUrlValue
                        onTextChanged: root.cloudUrlValue = text
                        placeholderText: "http://192.168.x.x:8000"
                        selectByMouse: true
                    }

                    Text { text: "8-character pairing code"; color: "#475569"; font.bold: true; font.pixelSize: 13 }
                    TextField {
                        width: parent.width
                        text: root.pairingCodeValue
                        onTextChanged: root.pairingCodeValue = text
                        placeholderText: "e.g. K9X4-M2P8"
                        selectByMouse: true
                        font.family: "monospace"
                        font.pixelSize: 18
                    }

                    Row {
                        anchors.horizontalCenter: parent.horizontalCenter
                        spacing: 10
                        Button {
                            width: 190; height: 42
                            text: "Pair & Start"
                            enabled: root.cloudUrlValue.length > 0 && root.pairingCodeValue.length >= 6
                            onClicked: root.claimRequested(root.cloudUrlValue, root.pairingCodeValue, root.remotePushValue)
                            background: Rectangle { radius: 8; color: parent.enabled ? "#111827" : "#94a3b8" }
                            contentItem: Text { text: parent.text; color: "#ffffff"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                        }
                        Button {
                            height: 42
                            text: "← Back to QR Scan"
                            onClicked: root.setupMode = "qr"
                        }
                    }
                }

                // ── FALLBACK 2: MANUAL DEVICE ID & SECRET ─────────────────────
                Column {
                    visible: root.firstTimeSetup && root.setupMode === "manual"
                    width: parent.width
                    spacing: 8

                    Text { text: "Cloud dashboard URL"; color: "#475569"; font.bold: true; font.pixelSize: 13 }
                    TextField {
                        width: parent.width
                        text: root.cloudUrlValue
                        onTextChanged: root.cloudUrlValue = text
                        placeholderText: "http://192.168.x.x:8000"
                        selectByMouse: true
                    }

                    Text { text: "Generated device ID"; color: "#475569"; font.bold: true; font.pixelSize: 13 }
                    TextField {
                        width: parent.width
                        text: root.deviceIdValue
                        onTextChanged: root.deviceIdValue = text
                        placeholderText: "Paste Device ID"
                        selectByMouse: true
                        font.family: "monospace"
                    }

                    Text { text: "One-time device secret"; color: "#475569"; font.bold: true; font.pixelSize: 13 }
                    TextField {
                        width: parent.width
                        text: root.deviceSecretValue
                        onTextChanged: root.deviceSecretValue = text
                        placeholderText: "Paste one-time secret"
                        selectByMouse: true
                        echoMode: TextInput.Password
                        font.family: "monospace"
                    }

                    Row {
                        anchors.horizontalCenter: parent.horizontalCenter
                        spacing: 10
                        Button {
                            width: 190; height: 42
                            text: "Verify & Start"
                            enabled: root.cloudUrlValue.length > 0 && root.deviceIdValue.length > 0 && root.deviceSecretValue.length > 0
                            onClicked: root.provisionRequested(root.cloudUrlValue, root.deviceIdValue, root.deviceSecretValue, root.remotePushValue)
                            background: Rectangle { radius: 8; color: parent.enabled ? "#111827" : "#94a3b8" }
                            contentItem: Text { text: parent.text; color: "#ffffff"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                        }
                        Button {
                            height: 42
                            text: "← Back to QR Scan"
                            onClicked: root.setupMode = "qr"
                        }
                    }
                }

                // ── NON-FIRST-TIME SETUP STATUS ───────────────────────────────
                Text {
                    visible: !root.firstTimeSetup
                    width: parent.width
                    text: statusText()
                    color: "#475569"
                    font.pixelSize: 14
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                }

                Text {
                    width: parent.width
                    visible: root.errorText.length > 0
                    text: root.errorText
                    color: "#b91c1c"
                    font.pixelSize: 13
                    font.bold: true
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                }

                Button {
                    visible: !root.firstTimeSetup
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 160; height: 42
                    text: "Refresh"
                    onClicked: root.refreshRequested()
                    background: Rectangle { radius: 8; color: "#111827" }
                    contentItem: Text { text: parent.text; color: "#ffffff"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                }
            }
        }
    }

    function statusText() {
        var parts = []
        if (!root.databaseOk) parts.push("SQLite database is not initialized or not readable.")
        if (!root.modelsOk) parts.push("Required face-recognition model files are missing.")
        return parts.length ? parts.join(" ") : "Checking device setup."
    }
}
