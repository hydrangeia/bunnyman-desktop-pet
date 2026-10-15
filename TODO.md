# Roadmap

## In place

- Three looks: normal, sleep cap, and sleep cap with pillow.
- Action controller for complete sleep, burrow, jump, walk/run, and recovery flows.
- Lively and quiet interaction schedules, feeding, hover, tap, drag, and menu controls.
- Manifest-driven frame loading and a bounded animation cache.
- Pure-Python regression tests for export geometry, action transitions, and interaction timing.
- Windows onedir build script, launcher smoke-test report, dependency pins, and source-check workflow are prepared.

## Still to verify before release

- Install the pinned dependencies in the clean project-local build environment and complete a Windows x64 onedir build.
- Build using the final manifest, then confirm the ZIP contains every referenced frame, prop, and effect and no unused render outputs.
- Run the packaged smoke test on the finished bundle and check snapping, sleep grounding, feed animation, and the pillow release sequence on a Windows desktop.
- Review the Klei asset use and third-party notices against the actual files included in the release.
- Publish the free fan-app bundle only after the app and included assets are ready.

## Later

- Keep the Chinese and English guides in sync as interactions and packaging settle.
- Revisit the desktop behavior based on real use, without promising accuracy or support that has not been tested.
