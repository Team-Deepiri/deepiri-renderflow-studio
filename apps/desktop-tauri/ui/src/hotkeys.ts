export type HotkeyDispatch = {
  jogBack: () => void;
  jogForward: () => void;
  shuttleBack: () => void;
  shuttleStop: () => void;
  shuttleForward: () => void;
  addMarker: () => void;
  splitClip: () => void;
  deleteClip: () => void;
  rippleDeleteClip: () => void;
  duplicateClip: () => void;
  undo: () => void;
  redo: () => void;
};

/**
 * Registers keyboard shortcuts for the studio.
 * Returns a cleanup function that removes the listener.
 *
 * Key map:
 *   ArrowLeft      → jog back 1 frame
 *   ArrowRight     → jog forward 1 frame
 *   j              → shuttle backward
 *   k              → shuttle stop
 *   l              → shuttle forward
 *   m              → add marker at playhead
 *   s              → split selected clip at playhead
 *   Delete / Backspace → delete selected clip
 *   Shift+Delete   → ripple delete (close the gap)
 *   Ctrl+D         → duplicate selected clip
 *   Ctrl+Z         → undo
 *   Ctrl+Y / Ctrl+Shift+Z → redo
 */
export function registerHotkeys(dispatch: HotkeyDispatch): () => void {
  const onKeyDown = (event: KeyboardEvent): void => {
    const target = event.target as HTMLElement;
    // Don't steal keystrokes from text inputs
    if (
      target instanceof HTMLInputElement ||
      target instanceof HTMLTextAreaElement
    ) {
      return;
    }

    const { key, ctrlKey, shiftKey } = event;

    if (ctrlKey && key === "z" && !shiftKey) {
      event.preventDefault();
      dispatch.undo();
      return;
    }
    if (ctrlKey && (key === "y" || (key === "z" && shiftKey))) {
      event.preventDefault();
      dispatch.redo();
      return;
    }
    if (ctrlKey && key === "d") {
      event.preventDefault();
      dispatch.duplicateClip();
      return;
    }

    switch (key) {
      case "ArrowLeft":
        event.preventDefault();
        dispatch.jogBack();
        break;
      case "ArrowRight":
        event.preventDefault();
        dispatch.jogForward();
        break;
      case "j":
        dispatch.shuttleBack();
        break;
      case "k":
        dispatch.shuttleStop();
        break;
      case "l":
        dispatch.shuttleForward();
        break;
      case "m":
        dispatch.addMarker();
        break;
      case "s":
        dispatch.splitClip();
        break;
      case "Delete":
      case "Backspace":
        if (shiftKey) dispatch.rippleDeleteClip();
        else dispatch.deleteClip();
        break;
    }
  };

  window.addEventListener("keydown", onKeyDown);
  return () => window.removeEventListener("keydown", onKeyDown);
}
