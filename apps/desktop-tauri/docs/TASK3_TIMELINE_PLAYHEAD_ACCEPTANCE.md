# Task 3 — Timeline + playhead acceptance

Manual checks in the desktop app (orchestrator running for import/place clip).

## Prerequisites

- Start orchestrator: `http://127.0.0.1:8080` healthy
- Launch Tauri desktop UI

## Checklist

1. **New Project → import → place clip**
   - Click **New Project**
   - Import a short video (path prompt or drag-drop)
   - Click the asset in the bin
   - Clip appears on the timeline at the playhead with correct span (`in_tick` = playhead, `out_tick` = playhead + duration)

2. **Scrub**
   - Drag the playhead slider
   - Clips under the playhead show `.active-clip`
   - Inspector lists **Active at playhead** entries
   - Release slider: native resolve runs (see `#out` JSON with `active_clip_ids`)

3. **Overlapping video (seed timeline)**
   - Without loading a project, use the built-in mock tracks
   - Scrub to tick **600** (V1 Main + V2 Overlay overlap)
   - Inspector order: **V2 Overlay** before **V1 Main** (lower `lane_index` on top)
   - Preview still image/stream uses the **overlay** asset when proxies exist

4. **Empty timeline region**
   - New Project (empty tracks) or scrub to a gap with no clips
   - Inspector: `Active at playhead: (none)`
   - Preview: **No clip at playhead**
   - `#out` shows `active_clip_ids: []` after resolve

5. **Play (1× stream)**
   - Place or use a clip with a ready proxy
   - Press **Play** (button)
   - Monitor shows video stream; playhead needle moves via `timeupdate`

6. **J / L shuttle (stills preview)**
   - With a ready proxy at the playhead, press **L** (forward 2×) or **J** (reverse 2×)
   - Playhead moves; monitor JPEG updates (~8 fps), not frozen
   - Press **K** to stop; final still frame at playhead

7. **Frame step**
   - **Arrow Left/Right** or **-1f / +1f**
   - Each step updates inspector and `#out` (`playhead_tick`, `active_clip_ids`)

8. **Shuttle at overlap (mock)**
   - Scrub to tick **600**, press **L** or **J**
   - Preview uses **top video** layer (V2 Overlay) per `getTopVideoActiveClip`

## Automated

From repo root:

```bash
cargo test -p timeline-engine-rs resolves_active_ordered_by_lane
cargo test -p timeline-engine-rs empty_sequence_has_no_active_clips
```
