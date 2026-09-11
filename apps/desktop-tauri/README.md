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

## Dev Mode

Unhides the devtools drawer and enables `devLog()` output (every backend call,
job poll, and export step). There is no UI toggle — run this in the webview
console:

```js
localStorage.setItem("deepiri_dev_mode", "true");
location.reload();
```

The reload is required: the flag is read once at startup in `ui/src/state.ts`.
Off again with `localStorage.removeItem("deepiri_dev_mode")` and a reload.
