# Mobile runtime channel boundary

This directory contains the Phase 3 Android Kotlin and iOS Swift plugin stubs.
Both sides use the channel names and method/event payloads declared in
`lib/models/mobile_runtime_contract.dart`:

- Method channel: `tw.fatigue_monitor/mobile_runtime`
- Event channel: `tw.fatigue_monitor/mobile_runtime/events`
- Events: `{type: "camera_frame", bytes, width, height, timestamp_micros, format}`
  and `{type: "foreground", state}`

The stubs implement foreground state and string local storage so the channel
boundary is testable. Camera capture, permission requests, and model loading
return `runtime_unavailable` until the Android/iOS native runtimes are built in
Phases 4 and 5. They do not invoke or bundle the desktop Python engine.

The current Flutter checkout is a Web/Tauri presentation project, so these
files are intentionally kept as plugin source for registration by the future
native runners. Creating signed Android/iOS applications and performing device
camera/inference validation remains outside Phase 3.
