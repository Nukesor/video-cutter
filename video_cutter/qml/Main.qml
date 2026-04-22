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
        currentFolder: backend.defaultOpenDirectoryUrl
        nameFilters: ["Video files (*.mp4 *.mov *.mkv *.webm *.avi *.m4v)", "All files (*)"]
        onAccepted: backend.openFile(selectedFile)
    }

    FolderDialog {
        id: saveDialog

        title: "Choose Output Directory"
        currentFolder: backend.defaultOutputDirectoryUrl
        onAccepted: backend.renderTo(selectedFolder)
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
                id: soundToggle

                text: "Disable Sound"
                checked: backend.muted
                onToggled: backend.setMuted(checked)

                contentItem: Text {
                    text: soundToggle.text
                    color: "#d9dde7"
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: soundToggle.indicator.width + soundToggle.spacing
                }
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
                        property string dragMode: ""
                        property point dragStart: Qt.point(0, 0)
                        property rect originalRect: Qt.rect(0, 0, 0, 0)
                        property rect draftRect: selectedRect
                        property real minSelectionSize: 8
                        property rect selectedRect: Qt.rect(
                            videoFrame.videoRect.x + crop.x * videoFrame.videoRect.width,
                            videoFrame.videoRect.y + crop.y * videoFrame.videoRect.height,
                            crop.width * videoFrame.videoRect.width,
                            crop.height * videoFrame.videoRect.height
                        )
                        property rect activeRect: dragMode.length > 0 ? draftRect : selectedRect

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

                        function insideActiveRect(x, y) {
                            return x >= activeRect.x && x <= activeRect.x + activeRect.width
                                && y >= activeRect.y && y <= activeRect.y + activeRect.height
                        }

                        function applyCrop(rect) {
                            backend.setSelectedCropNormalized(
                                (rect.x - videoFrame.videoRect.x) / videoFrame.videoRect.width,
                                (rect.y - videoFrame.videoRect.y) / videoFrame.videoRect.height,
                                rect.width / videoFrame.videoRect.width,
                                rect.height / videoFrame.videoRect.height
                            )
                        }

                        function beginEdit(mode, x, y) {
                            dragMode = mode
                            dragStart = Qt.point(clampX(x), clampY(y))
                            originalRect = selectedRect
                            draftRect = selectedRect
                            if (mode === "draw") {
                                draftRect = Qt.rect(dragStart.x, dragStart.y, 0, 0)
                            }
                        }

                        function updateDraft(x, y) {
                            const currentX = clampX(x)
                            const currentY = clampY(y)
                            const minX = videoFrame.videoRect.x
                            const minY = videoFrame.videoRect.y
                            const maxX = videoFrame.videoRect.x + videoFrame.videoRect.width
                            const maxY = videoFrame.videoRect.y + videoFrame.videoRect.height

                            if (dragMode === "draw") {
                                draftRect = Qt.rect(
                                    Math.min(dragStart.x, currentX),
                                    Math.min(dragStart.y, currentY),
                                    Math.abs(currentX - dragStart.x),
                                    Math.abs(currentY - dragStart.y)
                                )
                                return
                            }

                            if (dragMode === "move") {
                                const movedX = Math.max(minX, Math.min(maxX - originalRect.width, originalRect.x + currentX - dragStart.x))
                                const movedY = Math.max(minY, Math.min(maxY - originalRect.height, originalRect.y + currentY - dragStart.y))
                                draftRect = Qt.rect(movedX, movedY, originalRect.width, originalRect.height)
                                return
                            }

                            let left = originalRect.x
                            let right = originalRect.x + originalRect.width
                            let top = originalRect.y
                            let bottom = originalRect.y + originalRect.height

                            if (dragMode === "topLeft" || dragMode === "bottomLeft") {
                                left = Math.max(minX, Math.min(right - minSelectionSize, currentX))
                            }
                            if (dragMode === "topRight" || dragMode === "bottomRight") {
                                right = Math.min(maxX, Math.max(left + minSelectionSize, currentX))
                            }
                            if (dragMode === "topLeft" || dragMode === "topRight") {
                                top = Math.max(minY, Math.min(bottom - minSelectionSize, currentY))
                            }
                            if (dragMode === "bottomLeft" || dragMode === "bottomRight") {
                                bottom = Math.min(maxY, Math.max(top + minSelectionSize, currentY))
                            }

                            draftRect = Qt.rect(left, top, right - left, bottom - top)
                        }

                        function commitEdit() {
                            if (dragMode.length === 0) {
                                return
                            }

                            const mode = dragMode
                            dragMode = ""
                            if ((mode === "draw" || mode.indexOf("top") === 0 || mode.indexOf("bottom") === 0)
                                    && (draftRect.width < minSelectionSize || draftRect.height < minSelectionSize)) {
                                return
                            }
                            applyCrop(draftRect)
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

                        Rectangle {
                            x: cropOverlay.activeRect.x + 2
                            y: cropOverlay.activeRect.y + 2
                            z: 1
                            width: 14
                            height: 14
                            radius: 7
                            color: "#d9f5ff"
                            border.color: "#0b0d10"
                            border.width: 1

                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.SizeFDiagCursor
                                preventStealing: true

                                onPressed: function(mouse) {
                                    cropOverlay.beginEdit("topLeft", mouse.x + parent.x, mouse.y + parent.y)
                                }

                                onPositionChanged: function(mouse) {
                                    if (pressed) {
                                        cropOverlay.updateDraft(mouse.x + parent.x, mouse.y + parent.y)
                                    }
                                }

                                onReleased: cropOverlay.commitEdit()
                            }
                        }

                        Rectangle {
                            x: cropOverlay.activeRect.x + cropOverlay.activeRect.width - width - 2
                            y: cropOverlay.activeRect.y + 2
                            z: 1
                            width: 14
                            height: 14
                            radius: 7
                            color: "#d9f5ff"
                            border.color: "#0b0d10"
                            border.width: 1

                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.SizeBDiagCursor
                                preventStealing: true

                                onPressed: function(mouse) {
                                    cropOverlay.beginEdit("topRight", mouse.x + parent.x, mouse.y + parent.y)
                                }

                                onPositionChanged: function(mouse) {
                                    if (pressed) {
                                        cropOverlay.updateDraft(mouse.x + parent.x, mouse.y + parent.y)
                                    }
                                }

                                onReleased: cropOverlay.commitEdit()
                            }
                        }

                        Rectangle {
                            x: cropOverlay.activeRect.x + 2
                            y: cropOverlay.activeRect.y + cropOverlay.activeRect.height - height - 2
                            z: 1
                            width: 14
                            height: 14
                            radius: 7
                            color: "#d9f5ff"
                            border.color: "#0b0d10"
                            border.width: 1

                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.SizeBDiagCursor
                                preventStealing: true

                                onPressed: function(mouse) {
                                    cropOverlay.beginEdit("bottomLeft", mouse.x + parent.x, mouse.y + parent.y)
                                }

                                onPositionChanged: function(mouse) {
                                    if (pressed) {
                                        cropOverlay.updateDraft(mouse.x + parent.x, mouse.y + parent.y)
                                    }
                                }

                                onReleased: cropOverlay.commitEdit()
                            }
                        }

                        Rectangle {
                            x: cropOverlay.activeRect.x + cropOverlay.activeRect.width - width - 2
                            y: cropOverlay.activeRect.y + cropOverlay.activeRect.height - height - 2
                            z: 1
                            width: 14
                            height: 14
                            radius: 7
                            color: "#d9f5ff"
                            border.color: "#0b0d10"
                            border.width: 1

                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.SizeFDiagCursor
                                preventStealing: true

                                onPressed: function(mouse) {
                                    cropOverlay.beginEdit("bottomRight", mouse.x + parent.x, mouse.y + parent.y)
                                }

                                onPositionChanged: function(mouse) {
                                    if (pressed) {
                                        cropOverlay.updateDraft(mouse.x + parent.x, mouse.y + parent.y)
                                    }
                                }

                                onReleased: cropOverlay.commitEdit()
                            }
                        }

                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: !cropOverlay.insideVideo(mouseX, mouseY)
                                ? Qt.ArrowCursor
                                : cropOverlay.insideActiveRect(mouseX, mouseY)
                                    ? Qt.SizeAllCursor
                                    : Qt.CrossCursor

                            onPressed: function(mouse) {
                                if (!cropOverlay.insideVideo(mouse.x, mouse.y)) {
                                    return
                                }

                                if (cropOverlay.insideActiveRect(mouse.x, mouse.y)) {
                                    cropOverlay.beginEdit("move", mouse.x, mouse.y)
                                    return
                                }

                                cropOverlay.beginEdit("draw", mouse.x, mouse.y)
                            }

                            onPositionChanged: function(mouse) {
                                if (cropOverlay.dragMode.length === 0) {
                                    return
                                }

                                cropOverlay.updateDraft(mouse.x, mouse.y)
                            }

                            onReleased: function(mouse) {
                                if (cropOverlay.dragMode.length === 0) {
                                    return
                                }

                                cropOverlay.updateDraft(mouse.x, mouse.y)
                                cropOverlay.commitEdit()
                            }

                            onCanceled: cropOverlay.dragMode = ""
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
                                visible: !backend.hasSelectedSection
                                enabled: backend.hasSource && !backend.hasSelectedSection
                                onClicked: backend.markStart()
                            }

                            Button {
                                text: "Set End"
                                visible: !backend.hasSelectedSection
                                enabled: backend.hasSource && !backend.hasSelectedSection
                                onClicked: backend.markEnd()
                            }

                            Button {
                                text: "Add Section"
                                visible: !backend.hasSelectedSection
                                enabled: backend.hasSource && !backend.hasSelectedSection
                                onClicked: backend.addSectionFromMarkers()
                            }

                            Button {
                                text: "Clear Markers"
                                visible: !backend.hasSelectedSection
                                enabled: backend.hasSource && !backend.hasSelectedSection
                                onClicked: backend.clearMarkers()
                            }

                            Item {
                                Layout.fillWidth: true
                            }

                            Label {
                                text: backend.hasSelectedSection
                                    ? "Selected section " + window.formatSection(backend.pendingStart) + " - " + window.formatSection(backend.pendingEnd)
                                    : "Start " + window.formatSection(backend.pendingStart) + "  End " + window.formatSection(backend.pendingEnd)
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
                            ? "Drag the crop or its corner handles, then confirm to lock the current crop."
                            : "Create a section, then click it here to edit and confirm its crop."
                        color: "#97a0b0"
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        Button {
                            text: "Reset Crop To Full Frame"
                            enabled: backend.hasSelectedSection
                            onClicked: backend.resetSelectedCrop()
                        }

                        Button {
                            text: "Confirm Crop"
                            enabled: backend.hasSelectedSection
                            onClicked: backend.clearSelectedSection()
                        }
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
                            implicitHeight: Math.max(108, sectionCardLayout.implicitHeight + 24)

                            TapHandler {
                                onTapped: backend.selectSection(index)
                            }

                            ColumnLayout {
                                id: sectionCardLayout

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
                                    wrapMode: Text.WordWrap
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
