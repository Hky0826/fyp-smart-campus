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
    property string errorText: ""
    property string cloudUrlValue: setupCloudUrl || "http://127.0.0.1:8000"
    property string deviceIdValue: ""
    property string deviceSecretValue: ""
    property bool remotePushValue: false
    signal refreshRequested()
    signal setupCompleted()
    signal provisionRequested(string cloudUrl, string deviceId, string deviceSecret, bool remotePush)

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
        width: Math.min(760, parent.width - 36)
        height: root.firstTimeSetup ? 760 : 290
        radius: 10
        color: "#f8fafc"

        Flickable {
            anchors.fill: parent
            anchors.margins: 24
            contentWidth: width
            contentHeight: setupColumn.height
            clip: true

            Column {
                id: setupColumn
                width: parent.width
                spacing: 12

                Text {
                    width: parent.width
                    text: root.firstTimeSetup ? "Connect this access-control device" : "Device setup required"
                    color: "#0f172a"
                    font.pixelSize: 28
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                }

                Text {
                    width: parent.width
                    visible: root.firstTimeSetup
                    text: "Follow the steps below. SQLite is initialized automatically; you do not need to edit an .env file."
                    color: "#475569"
                    font.pixelSize: 15
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                }

                Rectangle {
                    visible: root.firstTimeSetup
                    width: parent.width
                    height: 98
                    radius: 8
                    color: "#e0f2fe"
                    border.color: "#7dd3fc"
                    Column {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 5
                        Text { text: "STEP 1 — NOTE THIS DEVICE ADDRESS"; color: "#075985"; font.bold: true; font.pixelSize: 12 }
                        Text { width: parent.width; text: "Detected edge address: " + (root.setupLocalAddress || "Not available"); color: "#0c4a6e"; font.family: "monospace"; font.bold: true }
                        Text { width: parent.width; text: "Automatic Wi-Fi address: " + (root.setupDetectedLanAddress || "Not available"); color: "#0c4a6e"; font.family: "monospace" }
                        Text { width: parent.width; text: "Use 127.0.0.1 when cloud and edge run on this laptop. For separate Wi-Fi devices, remote mode uses this device's detected LAN address."; color: "#0c4a6e"; wrapMode: Text.WordWrap }
                    }
                }

                Text {
                    visible: root.firstTimeSetup
                    width: parent.width
                    text: "STEP 2 — CREATE THE DEVICE IN THE ADMIN DASHBOARD"
                    color: "#334155"
                    font.bold: true
                    font.pixelSize: 12
                }
                Text {
                    visible: root.firstTimeSetup
                    width: parent.width
                    text: "Open the dashboard, choose Infrastructure → Devices → Add Device, complete the form, then copy the generated Device ID and one-time secret from the provisioning dialog."
                    color: "#475569"
                    wrapMode: Text.WordWrap
                }

                Text {
                    visible: root.firstTimeSetup
                    width: parent.width
                    text: "STEP 3 — ENTER THE DASHBOARD DETAILS HERE"
                    color: "#334155"
                    font.bold: true
                    font.pixelSize: 12
                }

                Text { visible: root.firstTimeSetup; text: "Cloud dashboard URL"; color: "#475569"; font.bold: true; font.pixelSize: 13 }
                TextField {
                    visible: root.firstTimeSetup
                    width: parent.width
                    text: root.cloudUrlValue
                    onTextChanged: root.cloudUrlValue = text
                    placeholderText: "http://127.0.0.1:8000"
                    selectByMouse: true
                }

                Text { visible: root.firstTimeSetup; text: "Generated device ID"; color: "#475569"; font.bold: true; font.pixelSize: 13 }
                TextField {
                    id: deviceIdField
                    visible: root.firstTimeSetup
                    width: parent.width
                    text: root.deviceIdValue
                    onTextChanged: root.deviceIdValue = text
                    placeholderText: "Paste the ID shown by the dashboard"
                    selectByMouse: true
                    font.family: "monospace"
                }

                Text { visible: root.firstTimeSetup; text: "One-time device secret"; color: "#475569"; font.bold: true; font.pixelSize: 13 }
                TextField {
                    visible: root.firstTimeSetup
                    width: parent.width
                    text: root.deviceSecretValue
                    onTextChanged: root.deviceSecretValue = text
                    placeholderText: "Paste the secret shown once by the dashboard"
                    selectByMouse: true
                    echoMode: TextInput.Password
                    font.family: "monospace"
                }

                Text {
                    visible: root.firstTimeSetup
                    width: parent.width
                    text: "The secret is saved by this device outside the project folder. Keep the dashboard dialog open until setup succeeds."
                    color: "#64748b"
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }

                CheckBox {
                    visible: root.firstTimeSetup
                    width: parent.width
                    text: "Enable secure cloud-to-edge push over Wi-Fi"
                    checked: root.remotePushValue
                    onCheckedChanged: root.remotePushValue = checked
                }

                Text {
                    visible: root.firstTimeSetup && root.remotePushValue
                    width: parent.width
                    text: "The device will automatically detect its LAN IP and use the device secret to authenticate cloud trigger messages. Use this only when cloud and edge are on separate computers."
                    color: "#64748b"
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }

                Text {
                    width: parent.width
                    text: root.firstTimeSetup ? "After setup succeeds, synchronization starts automatically and this screen closes." : statusText()
                    color: "#475569"
                    font.pixelSize: 14
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                }

                Text { width: parent.width; visible: root.errorText.length > 0; text: root.errorText; color: "#b91c1c"; font.pixelSize: 13; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter }

                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 10
                    Button {
                        width: 190; height: 44
                        text: root.firstTimeSetup ? "Apply and start" : "Refresh"
                        enabled: !root.firstTimeSetup || (root.cloudUrlValue.length > 0 && root.deviceIdValue.length > 0 && root.deviceSecretValue.length > 0)
                        onClicked: root.firstTimeSetup ? root.provisionRequested(root.cloudUrlValue, root.deviceIdValue, root.deviceSecretValue, root.remotePushValue) : root.refreshRequested()
                        background: Rectangle { radius: 8; color: parent.enabled ? "#111827" : "#94a3b8" }
                        contentItem: Text { text: parent.text; color: "#ffffff"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    }
                    Button {
                        visible: root.firstTimeSetup
                        width: 100; height: 44
                        text: "Refresh"
                        onClicked: root.refreshRequested()
                    }
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
