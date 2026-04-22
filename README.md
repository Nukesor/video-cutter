# Video Cutter

Simple desktop video cutter and cropper built with Python, PySide6/QML, libmpv, and ffmpeg.

Fully vibe-coded, but hey it works.

It's basically losslesscut, but with cropping. Try if it works for you, if not 🤷. No support planned.
From here on, the rest of the project and the readme is fully generated.
Good luck

## Features

- Preview video with libmpv embedded in Qt Quick
- Mark one or more start/stop sections on a simple timeline
- Assign a crop rectangle per section
- Disable audio on export
- Render each section through ffmpeg into a chosen output directory while keeping the source container extension

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
- Export writes one file per section using the naming scheme `{original_name}_section{sectionid}.{original_extension}`.
- The last used open directory and export directory are persisted in `~/.local/state/video_cutter.json`.
