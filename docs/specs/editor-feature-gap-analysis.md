# Video Editor Feature Gap Analysis

What standard NLEs (Premiere Pro, DaVinci Resolve, Final Cut Pro, CapCut,
Descript) give editors, measured against what Renderflow Studio has today.

Written 2026-08-12 alongside the home-page UX work. The "quick wins" section
was implemented in that same PR; everything else is a proposal, not a promise.

## What we already have

| Area | Shipped |
|---|---|
| Timeline | Video/audio tracks with lanes, zoom, playhead, markers |
| Clip editing | Split, delete, move (drag), trim (edge handles) |
| Transport | Play/pause, ±1 frame jog, J/K/L shuttle, scrub slider |
| History | Undo/redo across all timeline mutations |
| Media | Path import, drag-and-drop, proxy generation with polling, asset list |
| Monitor | Frame-accurate preview via ffmpeg, proxy video playback |
| AI | Prompt → job → stages → accept/reject → clip lands on the timeline |
| Export | Render jobs with a preset, progress reporting, output path |
| Projects | Templates, list/open/delete, sequences and server-side tracks |

## Gaps, by payoff

### Tier 1 — editors expect these and notice immediately

| Missing | Why it matters | Rough cost |
|---|---|---|
| **Copy / paste clips** | Ctrl+C/Ctrl+V is muscle memory. We have no clipboard at all. | S |
| **Multi-select** | Every operation is single-clip today; moving a scene means dragging clips one at a time. | M |
| **Audio waveforms on clips** | Audio editing is guesswork without them — you cannot cut to a beat or find a breath. | M (needs peak extraction + caching) |
| **Volume / gain per clip** | No way to balance music against dialog. The single most-requested basic audio control. | S–M |
| **Track mute / solo / lock** | The `Track` model already carries `muted`, `solo`, `locked`; nothing reads or renders them. | S (UI + honour them at render) |
| **Snapping** | ✅ shipped — see quick wins. | — |
| **Ripple delete** | ✅ shipped — see quick wins. | — |

### Tier 2 — the difference between a demo and a tool

| Missing | Why it matters | Rough cost |
|---|---|---|
| **Transitions** (cross dissolve, fade) | Hard cuts only, right now. Fade to/from black is table stakes. | M |
| **Titles / text overlays** | The most common single edit in social content. `V3 Titles` tracks exist in templates with no way to put text on them. | M–L |
| **Speed / retime UI** | `Clip.speed_ratio` is in the schema and honoured nowhere in the UI. | S–M |
| **Transform** (scale, position, crop) | Needed for the picture-in-picture the Tutorial template already implies. | M |
| **Source monitor with in/out** | Editors mark in/out before inserting; we can only append whole assets. | M |
| **Insert vs overwrite edit modes** | Standard three-point editing. | M |
| **Export range / custom settings** | One hardcoded `h264_1080p` preset, whole sequence only. No 9:16 social export despite a Social Clip template. | S–M |

### Tier 3 — differentiators, mostly AI-shaped

These are where an AI-native editor can beat the incumbents rather than
catch up to them. Current market expectation is transcription above ~95%
accuracy, usable auto-reframe, and scene detection that is right most of
the time.

- **Transcript-driven editing** (Descript's whole pitch) — cut video by
  deleting words. Plays directly to our AI backend.
- **Auto-captions / subtitles** — the `caption` and `subtitle` track types
  already exist in the schema and are unreachable from the UI.
- **Auto-reframe** to 9:16 / 1:1 from a 16:9 master.
- **Scene detection** to split a long take automatically.
- **Filler-word and silence removal.**
- **Voice isolation / noise reduction.**

### Tier 4 — infrastructure and trust

- **Autosave and crash recovery.** `saveProject` writes to localStorage on an
  explicit button press only; an app crash loses the session.
- **Timeline performance.** The current renderer rebuilds the whole grid on
  every mutation, including every pointermove during a drag. Fine at a few
  clips, not at a few hundred. Modern complaints about editors are about
  stutter and export time, not missing features.
- **Nested sequences**, **multicam**, and **collaboration** — real, but far
  past our current stage.

## Quick wins shipped in this PR

1. **Ripple delete** (`Shift+Del`, "Ripple" button) — removes a clip and pulls
   later clips on the same track back to close the gap. Plain `Del` still
   leaves the gap, because closing it is not always wanted.
2. **Duplicate clip** (`Ctrl+D`, "Duplicate" button) — copies the selected clip
   in directly after itself, then selects the copy.
3. **Snapping while dragging and trimming** — clip edges pull to neighbouring
   clip edges, the playhead, and zero within ~8px, scaled by zoom. Beyond that
   threshold, single-frame nudges still work.

Fixed along the way: dragging a clip applied a delta measured from the drag's
origin to the clip's *live* position on every pointer event, so drags
accelerated the further you moved. Drags are now positioned absolutely from
the drag origin.

## Suggested order

1. Copy/paste + multi-select — cheapest route to feeling like a real editor.
2. Track mute/solo/lock — the model is already there; it is UI plus honouring
   the flags at render.
3. Clip volume + audio waveforms — unblocks all audio work.
4. Titles and transitions — needed before anyone ships real content.
5. Autosave — before the first user loses a session.

## Sources

- [Ripple Delete definition — Adobe Premiere Pro](https://www.tella.com/definition/ripple-delete)
- [Ripple edit tool in Premiere Pro — Storyblocks](https://www.storyblocks.com/resources/tutorials/ripple-edit-tool-premiere-pro)
- [Final Cut Pro magnetic timeline — Filmora](https://filmora.wondershare.com/advanced-video-editing/final-cut-pro-magnetic-timeline.html)
- [Timeline panel in Premiere Pro, explained](https://filmit.io/blog/timeline-panel-premiere-pro-explained-for-editors)
- [Ripple delete across all tracks — CapCut community](https://www.capeditcut.com/community/video-editing/enhance-timeline-for-professional-editing-ripple-delete-across-all-tracks/)
- [Best video editing software 2026 — M Studio](https://mstudio.ai/blog/video-production/best-video-editing-software-2026-the-complete-guide-for-filmmakers)
- [Best video editing software 2026 — Vagon](https://vagon.io/blog/best-video-editing-software)
