/**
 * The Deepiri brand mark shown top-left in both the home and studio topbars.
 *
 * Loaded from `public/deepiri-logo.png`, so replacing the artwork is a file
 * drop — no code change. Keep the same filename, and keep the background
 * transparent: the topbar is dark.
 */
export const LOGO_SRC = "/deepiri-logo.png";

/**
 * Topbar brand block: Deepiri logo, then the product name with "Render" and
 * "Flow" carrying their own colors so each word reads independently.
 */
export function brandHtml(id: string, clickable = false): string {
  const attrs = clickable
    ? ` style="cursor:pointer" title="Back to Home"`
    : "";
  return `<div class="brand" id="${id}"${attrs}>
      <img class="brand-logo" src="${LOGO_SRC}" alt="Deepiri" width="30" height="30" />
      <span class="brand-text"><span class="word-render">Render</span><span class="word-flow">Flow</span> <span class="brand-sub">Studio</span></span>
    </div>`;
}
