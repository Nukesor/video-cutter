# Video Cutter

## Rough Spec

- Desktop app for trimming and cropping video files.
- Built with Python, PySide6, Qt Quick/QML, libmpv, and ffmpeg.
- Opens a local video file, previews it, and lets the user define one or more sections.
- Each section stores:
  - start time
  - end time
  - crop rectangle in normalized coordinates
- User can optionally remove audio from the export.
- Export is done by shelling out to `ffmpeg`.
- State is in-memory only. There is no project save/load support.
- The app persists the last used open directory and export directory in `~/.local/state/video_cutter.json`.

## User-Facing Behavior

- Main view shows a video preview area.
- Preview area shows a crop overlay only while a section is selected for editing.
- Timeline supports seeking and setting start/end markers for creating a new section.
- Selecting a section temporarily switches the UI into crop-edit mode for that section.
- Selecting a section also lets the user update that section's start and end markers from the main timeline controls.
- Crop editing supports drawing a new rectangle, dragging the current crop, and resizing from corner handles.
- Confirming the crop clears the current section selection so another section can be created.
- Right sidebar lists all currently defined sections.
- Selecting a section shows and edits that section's crop rectangle.
- Each section item includes a preview play action that plays only that section range and stops automatically at the section end.
- Export writes one rendered output file per section into a user-selected output directory.

## Current Architecture

### Entrypoint

- `main.py` delegates directly to `video_cutter.app:main`.

### App Bootstrap

- `video_cutter/app.py`
- Creates the `QApplication`.
- Forces Qt Quick to use the OpenGL graphics API.
- Registers the custom QML video item type.
- Instantiates the controller and exposes it to QML as `backend`.
- Exposes `previewEnabled` based on `VIDEO_CUTTER_DISABLE_PREVIEW`.

### Controller / State

- `video_cutter/controller.py`
- `VideoEditorController` is the central application object.
- Owns:
  - current source path
  - probed media metadata
  - playback state
  - pending markers for new-section creation
  - selected section index
  - render state/status text
  - `SectionsModel`
- Selected section markers are surfaced through the existing marker properties so the timeline can highlight the active section bounds.
- The controller also tracks optional bounded preview playback so a section can be reviewed in-place without affecting export state.
- Section data is represented by dataclasses:
  - `CropRect`
  - `Section`
  - `MediaInfo`

### Playback / Preview

- `video_cutter/mpv_item.py`
- Custom `QQuickFramebufferObject` used from QML.
- Renderer creates an `mpv.MpvRenderContext` for the controller's embedded player.
- OpenGL function addresses are resolved from the current Qt OpenGL context first, with GLX fallback.
- The renderer keeps a Python reference to the `QOpenGLFramebufferObject` to avoid premature wrapper destruction under PySide.

### Embedded mpv Setup

- The embedded player is created in `video_cutter/controller.py`.
- It is intentionally configured for app embedding rather than user CLI playback.
- Current options include:
  - `config=False`
  - `vo="libmpv"`
  - `hwdec="no"`
  - `osc=False`
  - `input_default_bindings=False`
  - `input_vo_keyboard=False`
- Goal: avoid host mpv config interfering with preview behavior.

### UI

- `video_cutter/qml/Main.qml`
- Contains:
  - video frame area
  - preview loader
  - crop overlay
  - playback controls
  - timeline/marker UI
  - section list
  - export controls/status
- Global keyboard shortcuts for play/pause and frame stepping are handled at the application level so they still work while controls like the timeline slider have focus.
- Preview is created through a `Loader` so it can be disabled entirely for debugging.
- The sidebar includes crop reset and crop confirm actions for the currently selected section.

### Export Pipeline

- Export logic lives in `video_cutter/controller.py`.
- Media metadata is probed with `ffprobe`.
- Rendering is executed through `QProcess` running `ffmpeg`.
- Rendering runs one ffmpeg job per section and names outputs as `{original_name}_section{sectionid}.{original_extension}`.

### Logging / Debugging

- `video_cutter/debug.py` provides environment-driven logging helpers.
- `.env` is automatically loaded by `just`.
- Common debug settings currently include:
  - `VIDEO_CUTTER_LOG=DEBUG`
  - `PYTHONFAULTHANDLER=1`
  - `QSG_INFO=1`
  - `QT_LOGGING_RULES=...`
  - `VIDEO_CUTTER_DISABLE_PREVIEW=0`

## Current Known Issue

- The main unresolved issue is native preview startup stability on the host graphics stack.
- The app runs when `VIDEO_CUTTER_DISABLE_PREVIEW=1`.
- That isolates the remaining startup crash to the preview/render path.
- Recent debugging indicates at least one crash path is in Qt's `QQuickFramebufferObject` / `QOpenGLFramebufferObject` handling rather than the Python controller itself.

## Important Assumptions

- `ffmpeg` and `ffprobe` are available on `PATH`.
- `libmpv` is installed on the system.
- The app currently targets local desktop usage only.
- No persistence or background job system exists.

## Files To Read First

- `main.py`
- `video_cutter/app.py`
- `video_cutter/controller.py`
- `video_cutter/mpv_item.py`
- `video_cutter/qml/Main.qml`
- `README.md`
