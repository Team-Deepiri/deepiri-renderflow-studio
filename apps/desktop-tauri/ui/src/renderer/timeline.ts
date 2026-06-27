import type { StudioState } from "../state";

export type TimelineCallbacks = {
  onTrackNameClick: (trackId: number) => void;
  onTrackDelete: (trackId: number) => void;
  onLaneClick: (trackId: number, tick: number) => void;
  onClipClick: (clipId: number, trackId: number) => void;
  onClipPointerDown: (
    clipId: number,
    trackId: number,
    mode: "move" | "trim-left" | "trim-right",
    event: PointerEvent,
    laneRect: DOMRect,
    scaledDuration: number
  ) => void;
};

/** Re-renders the full timeline grid into `root`. */
export function renderTimeline(
  state: StudioState,
  root: HTMLElement,
  timecodeEl: HTMLElement,
  sliderEl: HTMLInputElement,
  callbacks: TimelineCallbacks
): void {
  const { timeline, ui } = state;
  const scaledDuration = timeline.durationTicks * ui.zoom;
  root.innerHTML = "";

  for (const track of timeline.tracks) {
    const row = document.createElement("div");
    row.className = "track-row";
    if (track.id === ui.activeTrackId) row.classList.add("active");

    const nameEl = document.createElement("div");
    nameEl.className = "track-name";

    const nameLabel = document.createElement("span");
    nameLabel.className = "track-name-label";
    nameLabel.textContent = `${track.name} (${track.kind})`;
    nameLabel.addEventListener("click", () => callbacks.onTrackNameClick(track.id));

    const deleteBtn = document.createElement("button");
    deleteBtn.className = "track-delete";
    deleteBtn.textContent = "×";
    deleteBtn.title = "Delete track";
    deleteBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      callbacks.onTrackDelete(track.id);
    });

    nameEl.append(nameLabel, deleteBtn);

    const lane = document.createElement("div");
    lane.className = "track-lane";
    lane.addEventListener("click", (event) => {
      const rect = lane.getBoundingClientRect();
      const ratio = (event.clientX - rect.left) / rect.width;
      const tick = Math.round((ratio * scaledDuration) / ui.zoom);
      callbacks.onLaneClick(track.id, tick);
    });

    // Markers
    for (const markerTick of ui.markers) {
      const marker = document.createElement("div");
      marker.className = "marker";
      marker.style.left = `${((markerTick * ui.zoom) / scaledDuration) * 100}%`;
      lane.appendChild(marker);
    }

    // Clips
    for (const clip of track.clips) {
      const clipEl = buildClipElement(clip, track.id, ui.selectedClipId, scaledDuration, ui.zoom, lane, callbacks);
      lane.appendChild(clipEl);
    }

    // Playhead
    const playhead = document.createElement("div");
    playhead.className = "playhead";
    playhead.style.left = `${((timeline.playheadTick * ui.zoom) / scaledDuration) * 100}%`;
    lane.appendChild(playhead);

    row.append(nameEl, lane);
    root.appendChild(row);
  }

  // Update timecode and slider
  timecodeEl.textContent = formatTimecode(timeline.playheadTick, timeline.fps);
  sliderEl.value = String(timeline.playheadTick);
}

function buildClipElement(
  clip: { id: number; label: string; inTick: number; outTick: number; color: string },
  trackId: number,
  selectedClipId: number | null,
  scaledDuration: number,
  zoom: number,
  lane: HTMLElement,
  callbacks: TimelineCallbacks
): HTMLElement {
  const clipEl = document.createElement("div");
  clipEl.className = "clip";
  if (clip.id === selectedClipId) clipEl.classList.add("selected");

  clipEl.style.left = `${((clip.inTick * zoom) / scaledDuration) * 100}%`;
  clipEl.style.width = `${(((clip.outTick - clip.inTick) * zoom) / scaledDuration) * 100}%`;
  clipEl.style.background = clip.color;
  clipEl.textContent = clip.label;
  clipEl.draggable = false;

  clipEl.addEventListener("click", (e) => {
    e.stopPropagation();
    callbacks.onClipClick(clip.id, trackId);
  });

  const leftHandle = document.createElement("div");
  leftHandle.className = "trim-handle left";
  const rightHandle = document.createElement("div");
  rightHandle.className = "trim-handle right";
  clipEl.append(leftHandle, rightHandle);

  const startDrag = (e: PointerEvent, mode: "move" | "trim-left" | "trim-right") => {
    e.stopPropagation();
    e.preventDefault();
    callbacks.onClipPointerDown(clip.id, trackId, mode, e, lane.getBoundingClientRect(), scaledDuration);
  };

  clipEl.addEventListener("pointerdown", (e) => startDrag(e, "move"));
  leftHandle.addEventListener("pointerdown", (e) => startDrag(e, "trim-left"));
  rightHandle.addEventListener("pointerdown", (e) => startDrag(e, "trim-right"));

  return clipEl;
}

function formatTimecode(tick: number, fps: number): string {
  const total = Math.max(0, Math.floor(tick));
  const frames = total % fps;
  const totalSec = Math.floor(total / fps);
  const sec = totalSec % 60;
  const totalMin = Math.floor(totalSec / 60);
  const min = totalMin % 60;
  const hours = Math.floor(totalMin / 60);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(hours)}:${p(min)}:${p(sec)}:${p(frames)}`;
}
