import type { StudioState } from "../state";
import { getClipById } from "../ops/clips";

/** Updates the inspector panel with info about the currently selected clip. */
export function updateInspector(state: StudioState, el: HTMLElement): void {
  if (state.ui.selectedClipId == null) {
    el.textContent = "No clip selected.";
    return;
  }
  const found = getClipById(state, state.ui.selectedClipId);
  if (!found) {
    el.textContent = "Selected clip is no longer available.";
    return;
  }
  const { track, clip } = found;
  const duration = clip.outTick - clip.inTick;
  el.textContent = `${track.name}: ${clip.label} | in ${clip.inTick} | out ${clip.outTick} | len ${duration}f`;
}
