import QtQuick

Item {
    id: root
    property bool minimized: false
    property string sourceUrl: ""
    property int videoWidth: 0
    property int videoHeight: 0
    property var boxes: []

    x: minimized ? 10 : 0
    y: minimized ? 10 : 0
    width: minimized ? Math.max(0, Math.min(200, root.parent.width * 0.25) - 20) : root.parent.width
    height: minimized ? root.parent.height * 0.24 : root.parent.height
    z: minimized ? 35 : 0
    clip: true

    Behavior on x { NumberAnimation { duration: 180 } }
    Behavior on y { NumberAnimation { duration: 180 } }
    Behavior on width { NumberAnimation { duration: 180 } }
    Behavior on height { NumberAnimation { duration: 180 } }

    Rectangle {
        anchors.fill: parent
        color: "#020617"
        radius: root.minimized ? 8 : 0
        border.width: root.minimized ? 2 : 0
        border.color: root.minimized ? "#06b6d4" : "transparent"
    }

    Image {
        id: frame
        anchors.fill: parent
        source: root.sourceUrl
        cache: false
        fillMode: Image.PreserveAspectCrop
        mirror: true
        asynchronous: false
        smooth: true
    }

    Rectangle {
        anchors.fill: parent
        visible: !root.minimized
        color: "transparent"
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#33020617" }
            GradientStop { position: 0.55; color: "#00020617" }
            GradientStop { position: 1.0; color: "#33020617" }
        }
    }

    Repeater {
        model: root.boxes || []
        delegate: Rectangle {
            property var mapped: root.mapBox(modelData)
            x: mapped.x
            y: mapped.y
            width: mapped.width
            height: mapped.height
            radius: root.minimized ? 4 : 6
            color: "transparent"
            border.width: root.minimized ? 2 : 3
            border.color: "#5eead4"
            visible: mapped.width > 0 && mapped.height > 0
        }
    }

    function mapBox(box) {
        if (!box || box.length < 4 || root.videoWidth <= 0 || root.videoHeight <= 0) {
            return { "x": 0, "y": 0, "width": 0, "height": 0 }
        }
        var x1 = Number(box[0])
        var y1 = Number(box[1])
        var x2 = Number(box[2])
        var y2 = Number(box[3])
        var scale = Math.max(root.width / root.videoWidth, root.height / root.videoHeight)
        var drawnWidth = root.videoWidth * scale
        var drawnHeight = root.videoHeight * scale
        var offsetX = (root.width - drawnWidth) / 2
        var offsetY = (root.height - drawnHeight) / 2
        return {
            "x": offsetX + (root.videoWidth - x2) * scale,
            "y": offsetY + y1 * scale,
            "width": Math.max(0, (x2 - x1) * scale),
            "height": Math.max(0, (y2 - y1) * scale)
        }
    }
}

