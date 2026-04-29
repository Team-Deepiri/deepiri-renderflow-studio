# desktop-tauri

Tauri shell for Deepiri Renderflow Studio native desktop app.

Target layout:
- left: project files / asset explorer,
- center: Vulkan preview + timeline,
- right: AI copilot panel (collapsible for no-AI mode),
- bottom: inspector, keyframes, mixer, render jobs.

This directory will host:
- Tauri config and Rust commands bridge,
- desktop UI host and state container,
- IPC bindings to gRPC services and native core modules.
