# Video Cutter

Simple desktop video cutter and cropper built with Python, PySide6/QML, libmpv, and ffmpeg.

## Features

- Preview video with libmpv embedded in Qt Quick
- Mark one or more start/stop sections on a simple timeline
- Assign a crop rectangle per section
- Disable audio on export
- Render through ffmpeg while keeping the source container and codec names

## Requirements

- `ffmpeg` and `ffprobe` available on `PATH`
- `libmpv` installed on the system
- project dependencies installed through `uv`

## Commands

```bash
just run
just lint
just format
```

## Debug Run

Use verbose application logging during manual testing:

```bash
just run
```

This prints:

- app startup/QML warnings
- mpv log messages
- file open / marker / section / crop actions
- ffmpeg command launch and final output

Debug environment is stored in `.env` and loaded automatically by `just`.

If startup still segfaults, first isolate the preview path by changing:

```bash
VIDEO_CUTTER_DISABLE_PREVIEW=1
```

in `.env`, then run again. If the app starts with preview disabled, the crash is in the Qt Quick / OpenGL / libmpv render integration.

## Notes

- State is fully in-memory; closing the app loses the current edit session.
- Rendering pads smaller per-section crops to the largest crop size so multiple cropped sections can be concatenated into one output file.
