# Deepiri Renderflow Studio

Native animation and post-production studio for video editing, compositing, motion graphics, and 3D workflows.

## Principles

- Native-first desktop architecture (`Tauri` + Rust/C++ core).
- Vulkan-first rendering pipeline.
- Optional AI copilot with full manual/no-AI parity.
- Reuse Deepiri internals by vendoring/adapting code instead of direct imports.

## Monorepo Layout

- `apps/desktop-tauri`: desktop shell and editor UI host.
- `core/timeline-engine-rs`: deterministic timeline and playback math.
- `core/render-engine-vulkan`: render graph and GPU orchestration.
- `core/audio-engine-juce`: JUCE integration boundary for audio graph.
- `services/ai-orchestrator-fastapi`: job orchestration and API.
- `services/model-workers-pytorch`: model worker entrypoints.
- `proto/grpc`: gRPC contracts for desktop<->services IPC.
- `infra/postgres/migrations`: SQL schema.
- `vendor/deepiri`: copied/adapted Deepiri modules.

## Getting Started (bootstrap)

1. Build timeline crate:
   - `cargo test --manifest-path core/timeline-engine-rs/Cargo.toml`
2. Run AI orchestrator:
   - `python -m venv .venv && source .venv/bin/activate`
   - `pip install -r services/ai-orchestrator-fastapi/requirements.txt`
   - `uvicorn app.main:app --app-dir services/ai-orchestrator-fastapi --reload`
3. Run model worker:
   - `python services/model-workers-pytorch/app/worker.py`

## Vendoring Policy

Deepiri code under `vendor/deepiri/*` must include:
- origin module path,
- source commit/hash where available,
- adaptation notes for Renderflow.
# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the ESLint configuration

If you are developing a production application, we recommend updating the configuration to enable type-aware lint rules:

```js
export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Other configs...

      // Remove tseslint.configs.recommended and replace with this
      tseslint.configs.recommendedTypeChecked,
      // Alternatively, use this for stricter rules
      tseslint.configs.strictTypeChecked,
      // Optionally, add this for stylistic rules
      tseslint.configs.stylisticTypeChecked,

      // Other configs...
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // other options...
    },
  },
])
```

You can also install [eslint-plugin-react-x](https://github.com/Rel1cx/eslint-react/tree/main/packages/plugins/eslint-plugin-react-x) and [eslint-plugin-react-dom](https://github.com/Rel1cx/eslint-react/tree/main/packages/plugins/eslint-plugin-react-dom) for React-specific lint rules:

```js
// eslint.config.js
import reactX from 'eslint-plugin-react-x'
import reactDom from 'eslint-plugin-react-dom'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Other configs...
      // Enable lint rules for React
      reactX.configs['recommended-typescript'],
      // Enable lint rules for React DOM
      reactDom.configs.recommended,
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // other options...
    },
  },
])
```
