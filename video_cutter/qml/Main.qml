import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import VideoCutter 1.0

ApplicationWindow {
    id: window

    width: 1440
    height: 900
    visible: true
    color: "#15161a"
    title: backend.sourceName.length > 0 ? backend.sourceName + " - Video Cutter" : "Video Cutter"

    function formatSection(value) {
        if (value < 0) {
            return "--:--"
        }

        let total = Math.max(0, Math.floor(value))
        const hours = Math.floor(total / 3600)
        total -= hours * 3600
        const minutes = Math.floor(total / 60)
        const seconds = total % 60

        const mm = String(minutes).padStart(2, "0")
        const ss = String(seconds).padStart(2, "0")
        if (hours > 0) {
            return String(hours).padStart(2, "0") + ":" + mm + ":" + ss
        }
        return mm + ":" + ss
    }

    FileDialog {
        id: openDialog

        title: "Open Video"
        fileMode: FileDialog.OpenFile
        nameFilters: ["Video files (*.mp4 *.mov *.mkv *.webm *.avi *.m4v)", "All files (*)"]
        onAccepted: backend.openFile(selectedFile)
    }

    FileDialog {
        id: saveDialog

        title: "Render Video"
        fileMode: FileDialog.SaveFile
        currentFile: backend.defaultOutputFileUrl
        onAccepted: backend.renderTo(selectedFile)
    }

    header: ToolBar {
        background: Rectangle {
            color: "#1e2026"
        }

        RowLayout {
            anchors.fill: parent
            anchors.margins: 10
            spacing: 10

            Button {
                text: "Open Video"
                onClicked: openDialog.open()
            }

            CheckBox {
                text: "Disable Sound"
                checked: backend.muted
                onToggled: backend.setMuted(checked)
            }

            Button {
                text: backend.rendering ? "Rendering..." : "Render"
                enabled: backend.canRender
                onClicked: saveDialog.open()
            }

            Item {
                Layout.fillWidth: true
            }

            Label {
                text: backend.sourceName.length > 0 ? backend.sourceName : "No file loaded"
                color: "#d9dde7"
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        color: "#15161a"

        RowLayout {
            anchors.fill: parent
            anchors.margins: 14
            spacing: 14

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 12

                Rectangle {
                    id: videoFrame

                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: 16
                    color: "#0b0d10"
                    border.color: "#2a2d35"
                    border.width: 1
                    clip: true

                    property real videoAspect: backend.videoHeight > 0 ? backend.videoWidth / backend.videoHeight : 16 / 9
                    property rect videoRect: {
                        const itemAspect = width / Math.max(height, 1)
                        if (itemAspect > videoAspect) {
                            const videoWidth = height * videoAspect
                            return Qt.rect((width - videoWidth) / 2, 0, videoWidth, height)
                        }

                        const videoHeight = width / videoAspect
                        return Qt.rect(0, (height - videoHeight) / 2, width, videoHeight)
                    }

                    Loader {
                        anchors.fill: parent
                        active: previewEnabled
                        sourceComponent: MpvVideoItem {
                            controller: backend
                        }
                    }

                    Rectangle {
                        anchors.fill: parent
                        color: "transparent"
                        visible: !backend.hasSource || !previewEnabled

                        Label {
                            anchors.centerIn: parent
                            text: previewEnabled
                                ? "Open a video to preview and edit sections"
                                : "Preview disabled in .env. Set VIDEO_CUTTER_DISABLE_PREVIEW=0 to re-enable it."
                            color: "#7e8797"
                            font.pixelSize: 18
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.WordWrap
                            width: parent.width * 0.6
                        }
                    }

                    Item {
                        id: cropOverlay

                        anchors.fill: parent
                        visible: backend.hasSelectedSection && backend.hasSource

                        property var crop: backend.selectedCrop
                        property real dragStartX: 0
                        property real dragStartY: 0
                        property real dragX: 0
                        property real dragY: 0
                        property bool dragging: false
                        property rect selectedRect: Qt.rect(
                            videoFrame.videoRect.x + crop.x * videoFrame.videoRect.width,
                            videoFrame.videoRect.y + crop.y * videoFrame.videoRect.height,
                            crop.width * videoFrame.videoRect.width,
                            crop.height * videoFrame.videoRect.height
                        )
                        property rect activeRect: dragging
                            ? Qt.rect(
                                Math.min(dragStartX, dragX),
                                Math.min(dragStartY, dragY),
                                Math.abs(dragX - dragStartX),
                                Math.abs(dragY - dragStartY)
                            )
                            : selectedRect

                        function clampX(value) {
                            return Math.max(videoFrame.videoRect.x, Math.min(videoFrame.videoRect.x + videoFrame.videoRect.width, value))
                        }

                        function clampY(value) {
                            return Math.max(videoFrame.videoRect.y, Math.min(videoFrame.videoRect.y + videoFrame.videoRect.height, value))
                        }

                        function insideVideo(x, y) {
                            return x >= videoFrame.videoRect.x && x <= videoFrame.videoRect.x + videoFrame.videoRect.width
                                && y >= videoFrame.videoRect.y && y <= videoFrame.videoRect.y + videoFrame.videoRect.height
                        }

                        Rectangle {
                            x: videoFrame.videoRect.x
                            y: videoFrame.videoRect.y
                            width: videoFrame.videoRect.width
                            height: Math.max(0, cropOverlay.activeRect.y - videoFrame.videoRect.y)
                            color: "#80000000"
                        }

                        Rectangle {
                            x: videoFrame.videoRect.x
                            y: cropOverlay.activeRect.y
                            width: Math.max(0, cropOverlay.activeRect.x - videoFrame.videoRect.x)
                            height: cropOverlay.activeRect.height
                            color: "#80000000"
                        }

                        Rectangle {
                            x: cropOverlay.activeRect.x + cropOverlay.activeRect.width
                            y: cropOverlay.activeRect.y
                            width: Math.max(0, videoFrame.videoRect.x + videoFrame.videoRect.width - (cropOverlay.activeRect.x + cropOverlay.activeRect.width))
                            height: cropOverlay.activeRect.height
                            color: "#80000000"
                        }

                        Rectangle {
                            x: videoFrame.videoRect.x
                            y: cropOverlay.activeRect.y + cropOverlay.activeRect.height
                            width: videoFrame.videoRect.width
                            height: Math.max(0, videoFrame.videoRect.y + videoFrame.videoRect.height - (cropOverlay.activeRect.y + cropOverlay.activeRect.height))
                            color: "#80000000"
                        }

                        Rectangle {
                            x: cropOverlay.activeRect.x
                            y: cropOverlay.activeRect.y
                            width: cropOverlay.activeRect.width
                            height: cropOverlay.activeRect.height
                            color: "transparent"
                            border.color: "#6ed4ff"
                            border.width: 2
                        }

                        Label {
                            x: cropOverlay.activeRect.x + 8
                            y: Math.max(videoFrame.videoRect.y + 8, cropOverlay.activeRect.y + 8)
                            text: "Crop"
                            color: "#d9f5ff"
                            visible: cropOverlay.activeRect.width > 48 && cropOverlay.activeRect.height > 22
                        }

                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: cropOverlay.insideVideo(mouseX, mouseY) ? Qt.CrossCursor : Qt.ArrowCursor

                            onPressed: function(mouse) {
                                if (!cropOverlay.insideVideo(mouse.x, mouse.y)) {
                                    return
                                }

                                cropOverlay.dragging = true
                                cropOverlay.dragStartX = cropOverlay.clampX(mouse.x)
                                cropOverlay.dragStartY = cropOverlay.clampY(mouse.y)
                                cropOverlay.dragX = cropOverlay.dragStartX
                                cropOverlay.dragY = cropOverlay.dragStartY
                            }

                            onPositionChanged: function(mouse) {
                                if (!cropOverlay.dragging) {
                                    return
                                }

                                cropOverlay.dragX = cropOverlay.clampX(mouse.x)
                                cropOverlay.dragY = cropOverlay.clampY(mouse.y)
                            }

                            onReleased: function(mouse) {
                                if (!cropOverlay.dragging) {
                                    return
                                }

                                cropOverlay.dragX = cropOverlay.clampX(mouse.x)
                                cropOverlay.dragY = cropOverlay.clampY(mouse.y)
                                cropOverlay.dragging = false

                                const width = Math.abs(cropOverlay.dragX - cropOverlay.dragStartX)
                                const height = Math.abs(cropOverlay.dragY - cropOverlay.dragStartY)
                                if (width < 8 || height < 8) {
                                    return
                                }

                                const x = Math.min(cropOverlay.dragStartX, cropOverlay.dragX)
                                const y = Math.min(cropOverlay.dragStartY, cropOverlay.dragY)
                                backend.setSelectedCropNormalized(
                                    (x - videoFrame.videoRect.x) / videoFrame.videoRect.width,
                                    (y - videoFrame.videoRect.y) / videoFrame.videoRect.height,
                                    width / videoFrame.videoRect.width,
                                    height / videoFrame.videoRect.height
                                )
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    radius: 16
                    color: "#1b1d24"
                    border.color: "#2a2d35"
                    border.width: 1
                    implicitHeight: 220

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 12

                        Label {
                            text: backend.positionLabel + " / " + backend.durationLabel
                            color: "#d9dde7"
                            font.pixelSize: 18
                        }

                        Item {
                            Layout.fillWidth: true
                            implicitHeight: 56

                            Slider {
                                id: timelineSlider

                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: parent.top
                                from: 0
                                to: Math.max(backend.duration, 0.001)
                                value: pressed ? value : backend.position
                                enabled: backend.hasSource

                                onMoved: backend.seekTo(value)
                            }

                            Rectangle {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                height: 18
                                radius: 9
                                color: "#11131a"

                                Repeater {
                                    model: backend.sectionsModel

                                    Rectangle {
                                        x: backend.duration > 0 ? (start / backend.duration) * parent.width : 0
                                        width: backend.duration > 0 ? Math.max(4, ((end - start) / backend.duration) * parent.width) : 0
                                        height: parent.height
                                        radius: 9
                                        color: index === backend.selectedSectionIndex ? "#6ed4ff" : "#425a74"
                                    }
                                }

                                Rectangle {
                                    visible: backend.pendingStart >= 0 && backend.duration > 0
                                    x: (backend.pendingStart / backend.duration) * parent.width - width / 2
                                    width: 3
                                    height: parent.height
                                    radius: 2
                                    color: "#40e08d"
                                }

                                Rectangle {
                                    visible: backend.pendingEnd >= 0 && backend.duration > 0
                                    x: (backend.pendingEnd / backend.duration) * parent.width - width / 2
                                    width: 3
                                    height: parent.height
                                    radius: 2
                                    color: "#ff7b72"
                                }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8

                            Button {
                                text: backend.playing ? "Pause" : "Play"
                                enabled: backend.hasSource
                                onClicked: backend.togglePlayback()
                            }

                            Button {
                                text: "Set Start"
                                enabled: backend.hasSource
                                onClicked: backend.markStart()
                            }

                            Button {
                                text: "Set End"
                                enabled: backend.hasSource
                                onClicked: backend.markEnd()
                            }

                            Button {
                                text: "Add Section"
                                enabled: backend.hasSource
                                onClicked: backend.addSectionFromMarkers()
                            }

                            Button {
                                text: "Clear Markers"
                                enabled: backend.hasSource
                                onClicked: backend.clearMarkers()
                            }

                            Item {
                                Layout.fillWidth: true
                            }

                            Label {
                                text: "Start " + window.formatSection(backend.pendingStart) + "  End " + window.formatSection(backend.pendingEnd)
                                color: "#97a0b0"
                            }
                        }
                    }
                }
            }

            Rectangle {
                Layout.preferredWidth: 330
                Layout.fillHeight: true
                radius: 16
                color: "#1b1d24"
                border.color: "#2a2d35"
                border.width: 1

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 12

                    Label {
                        text: "Selected Sections"
                        color: "#d9dde7"
                        font.pixelSize: 20
                    }

                    Label {
                        text: backend.hasSelectedSection
                            ? "Drag on the preview to change the crop for the selected section."
                            : "Create a section, then click it here to edit its crop."
                        color: "#97a0b0"
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }

                    Button {
                        text: "Reset Crop To Full Frame"
                        enabled: backend.hasSelectedSection
                        onClicked: backend.resetSelectedCrop()
                    }

                    ListView {
                        id: sectionsList

                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 8
                        model: backend.sectionsModel

                        delegate: Rectangle {
                            width: sectionsList.width
                            radius: 12
                            color: index === backend.selectedSectionIndex ? "#25354a" : "#22252d"
                            border.color: index === backend.selectedSectionIndex ? "#6ed4ff" : "#313540"
                            border.width: 1
                            implicitHeight: 96

                            TapHandler {
                                onTapped: backend.selectSection(index)
                            }

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 12
                                spacing: 6

                                RowLayout {
                                    Layout.fillWidth: true

                                    Label {
                                        text: "Section " + (index + 1)
                                        color: "#eef4ff"
                                        font.bold: true
                                    }

                                    Item {
                                        Layout.fillWidth: true
                                    }

                                    Button {
                                        text: "Remove"
                                        onClicked: backend.removeSection(index)
                                    }
                                }

                                Label {
                                    text: label
                                    color: "#d9dde7"
                                }

                                Label {
                                    text: "Duration " + window.formatSection(duration)
                                    color: "#97a0b0"
                                }

                                Label {
                                    text: cropSummary
                                    color: "#97a0b0"
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        radius: 12
                        color: "#12141a"
                        border.color: "#2a2d35"
                        border.width: 1
                        implicitHeight: 76

                        Label {
                            anchors.fill: parent
                            anchors.margins: 12
                            text: backend.statusText
                            color: "#bfc7d5"
                            wrapMode: Text.WordWrap
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }
            }
        }
    }
}
