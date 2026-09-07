const HTML_ENTITIES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

/**
 * Escapes text that gets interpolated into an innerHTML template.
 *
 * Project names, asset names and clip labels are user-authored — AI project
 * names are the prompt itself — and this is a desktop webview, so injected
 * markup would run with the app's privileges.
 */
export function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (ch) => HTML_ENTITIES[ch]);
}
