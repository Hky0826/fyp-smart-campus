import QtQuick
import QtQuick.Controls

Button {
    id: root
    property string mode: "idle"
    property real dwellProgress: 0.0
    readonly property bool accessResult: mode === "access-granted" || mode === "access-denied"
    readonly property color glowColor: mode === "access-granted" ? "#22c55e" : "#ef4444"

    width: 64
    height: 64
    padding: 0
    text: ""

    Rectangle {
        id: dwellBadge
        anchors.bottom: parent.top
        anchors.bottomMargin: 10
        anchors.horizontalCenter: parent.horizontalCenter
        width: badgeText.implicitWidth + 18
        height: 28
        radius: 14
        color: "#0f172a"
        border.color: "#38bdf8"
        border.width: 1
        visible: root.dwellProgress > 0.05 && !root.accessResult
        opacity: Math.min(1.0, (root.dwellProgress - 0.05) * 3.0)

        Text {
            id: badgeText
            anchors.centerIn: parent
            text: "Ready when you are…"
            color: "#38bdf8"
            font.pixelSize: 12
            font.bold: true
        }

        Behavior on opacity { NumberAnimation { duration: 150 } }
    }

    Canvas {
        id: progressCanvas
        anchors.centerIn: parent
        width: parent.width + 16
        height: parent.height + 16
        z: 60
        visible: root.dwellProgress > 0.0 && !root.accessResult
        opacity: Math.min(1.0, root.dwellProgress * 2.0)

        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            var centerX = width / 2;
            var centerY = height / 2;
            var radius = width / 2 - 4;

            // Subtle background track
            ctx.beginPath();
            ctx.arc(centerX, centerY, radius, 0, 2 * Math.PI, false);
            ctx.lineWidth = 3;
            ctx.strokeStyle = "rgba(56, 189, 248, 0.25)";
            ctx.stroke();

            // Progress arc
            if (root.dwellProgress > 0.0) {
                var startAngle = -0.5 * Math.PI;
                var endAngle = startAngle + (root.dwellProgress * 2.0 * Math.PI);
                ctx.beginPath();
                ctx.arc(centerX, centerY, radius, startAngle, endAngle, false);
                ctx.lineWidth = 4;
                ctx.strokeStyle = "#38bdf8";
                ctx.lineCap = "round";
                ctx.stroke();
            }
        }

        Connections {
            target: root
            function onDwellProgressChanged() {
                progressCanvas.requestPaint();
            }
        }
    }

    background: Rectangle {
        radius: width / 2
        color: root.enabled ? "#f8fafc" : "#94a3b8"
        border.width: root.accessResult ? 3 : 0
        border.color: root.accessResult ? root.glowColor : "transparent"

        Rectangle {
            anchors.centerIn: parent
            width: parent.width + 24
            height: parent.height + 24
            radius: width / 2
            color: "transparent"
            border.width: root.accessResult ? 8 : 0
            border.color: root.accessResult ? root.glowColor : "transparent"
            opacity: root.accessResult ? 0.34 : 0

            SequentialAnimation on opacity {
                running: root.accessResult
                loops: Animation.Infinite
                NumberAnimation { to: 0.12; duration: 520 }
                NumberAnimation { to: 0.34; duration: 520 }
            }
        }
    }

    contentItem: Item {
        Rectangle {
            id: bubble
            anchors.centerIn: parent
            width: 30
            height: 24
            radius: 8
            color: "transparent"
            border.width: 3
            border.color: "#0f172a"
        }

        Rectangle {
            width: 10
            height: 10
            x: bubble.x + 5
            y: bubble.y + bubble.height - 3
            rotation: 45
            color: root.enabled ? "#f8fafc" : "#94a3b8"
            border.width: 3
            border.color: "#0f172a"
        }

        Rectangle {
            width: 14
            height: 8
            x: bubble.x + 2
            y: bubble.y + bubble.height - 5
            color: root.enabled ? "#f8fafc" : "#94a3b8"
        }
    }
}
