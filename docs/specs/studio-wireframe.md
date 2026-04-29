# Studio UI Wireframe (Native)

```text
+--------------------------------------------------------------------------------------------------+
| Menu  File Edit View Sequence Scene Audio AI Help                 Project: Film_01  [Render]   |
+--------------------------------------------------------------------------------------------------+
| Toolbar: [Select][Cut][Slip][Razor][Pen][Move] [Snap] [AutoRipple] [AI Create Scene]           |
+-----------------------------+------------------------------------------------+-------------------+
| AssetExplorer/ProjectFiles  |                 ProgramMonitor                 | AI Copilot        |
| - project/                  | +--------------------------------------------+ | Chat + Tasks      |
| - footage/                  | |            Vulkan Preview Canvas           | | [Create Scene]   |
| - audio/                    | |                                            | | [Generate Audio] |
| - scenes/                   | +--------------------------------------------+ | [Roto Assist]     |
| - exports/                  | TimelineControls: [Play][Stop][JKL][Loop]      | Stage Progress     |
+-----------------------------+------------------------------------------------+-------------------+
| TimelinePanel                                                                                   |
| V3 |----clip----|--fx--|----nested_seq----|                                                     |
| V2 |------title_motion_graphic------|                                                           |
| V1 |----main_footage-----------------------------|                                               |
| A2 |----music-------------------------|                                                          |
| A1 |----dialogue--------|---sfx---|                                                            |
+--------------------------------------------------------------------------------------------------+
| Inspector | EffectStack | Keyframes | Mixer | Console | BackgroundJobs | Export                |
+--------------------------------------------------------------------------------------------------+
```

## UX Rules

- AI outputs must become normal editable assets and timeline clips.
- Manual mode hides AI controls and keeps identical export/playback capability.
- All edits are non-destructive with versioned assets.
