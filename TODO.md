# Roadmap

## In place

- Three looks: normal, sleep cap, and sleep cap with pillow.
- Action controller for complete sleep, burrow, jump, walk/run, and recovery flows.
- Silent lively and quiet interaction schedules, visible carrot feeding, hover, body taps, double-clicks, dragging, and discoverable wheel/shake reactions.
- Screen/taskbar/ordinary-window edge docking, following moving windows, and sleep support based on the visible body outline.
- Pillow release transitions and independent hit, thaw, and pillow-petal effects.
- Manifest-driven frame loading and a bounded animation cache.
- 147 regression tests pass locally, including native Windows window-capture checks; the default Windows CI run has 146 passed and 1 skipped, without local game files.
- Windows x64 portable ZIP built in a clean project-local environment, with all 5,604 referenced images and dependency license texts.
- Packaged executable smoke checks pass in the bundle folder, after ZIP extraction into a Chinese/space-containing path, and after applying the update over v0.1.0: 99 clips, 55 clip names, 30 complete actions, and 5,603 animation/effect frames, including capture-view synchronization and lifecycle checks.
- Separate capture window with a fixed 620×616 canvas, synchronized pet/effect frames, and selectable green/blue/magenta backgrounds for streaming software.
- Bilingual build/download guides and a public source repository.

## Release

- Published [v0.1.1](https://github.com/hydrangeia/bunnyman-desktop-pet/releases/tag/v0.1.1) with the independent capture window, full bundle, and a 4.95 MB v0.1.0 update. Both GitHub asset digests match the tested ZIPs; applying the update produces the same program files as the full bundle.
- Published [v0.1.0](https://github.com/hydrangeia/bunnyman-desktop-pet/releases/tag/v0.1.0) with the portable ZIP and its SHA-256 checksum; GitHub's asset digest matches the tested local ZIP.

## Later

- Test window capture and chroma key end-to-end in OBS and Bilibili Live Companion on Windows.
- Try more window arrangements and mixed-DPI monitors during everyday use.
- Refine pillow motion and the timing of discoveries from play feedback.
- Walking and running currently stay in place; consider movement as a separate interaction milestone.
