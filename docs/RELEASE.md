# Releasing Renderflow Studio Desktop

GitHub Actions builds the Tauri desktop shell (`apps/desktop-tauri`) for Linux, macOS, and Windows when you push a version tag. Asset filenames match the [Deepiri landing site](https://github.com/Team-Deepiri/deepiri-landing).

## Cut a release

1. Merge changes to `main`.
2. Bump versions in `apps/desktop-tauri/src-tauri/Cargo.toml` and `tauri.conf.json` if needed (current: `0.1.0`).
3. Tag and push:

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

4. Watch [Release workflow](https://github.com/Team-Deepiri/deepiri-renderflow-studio/actions/workflows/release.yml).

## Test CI without tagging

**Actions → Release → Run workflow** on a branch. Publish is skipped unless the ref is a `v*` tag.

## Local packaging (optional)

Requires Node 22+, Rust stable, and platform Tauri deps (see main CI `desktop-tauri` job).

```bash
bash scripts/ci/build-release.sh
ls release/
```

## Release assets

| Platform | Filename |
|----------|----------|
| macOS | `Renderflow-Studio-latest.dmg` |
| Linux | `Renderflow-Studio-latest.AppImage` |
| Windows | `Renderflow-Studio-latest-setup.exe` |

## Verify download URLs

```bash
BASE=https://github.com/Team-Deepiri/deepiri-renderflow-studio/releases/latest/download

curl -I "$BASE/Renderflow-Studio-latest.dmg"
curl -I "$BASE/Renderflow-Studio-latest.AppImage"
curl -I "$BASE/Renderflow-Studio-latest-setup.exe"
```

## Notes

- The desktop app is the Tauri shell only; the Python orchestrator remains a separate service (see landing terminal install docs).
- CI generates Tauri icons on the fly (`scripts/ci/generate_tauri_icons.py`) because `tauri.conf.json` had no icon set checked in.
- v1 builds are **unsigned**; expect Gatekeeper / SmartScreen prompts.
- Linux builds require WebKitGTK and related packages (mirrors main CI).
