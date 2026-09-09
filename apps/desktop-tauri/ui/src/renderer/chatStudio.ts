import { brandHtml } from "./brand";

/**
 * STUB — Chat Studio (New Project interview).
 *
 * Placeholder for the ChatGPT-style onboarding interview described in
 * docs/Production-Readiness-1-Month-Plan.md ("Chat studio v1"): a guided
 * conversation that collects goal, length, scenes, and generate-vs-import
 * per scene, then hands off to the editor with that brief applied.
 *
 * There is no conversation logic yet — this is an empty-state shell so
 * "New project" has a real (if inert) destination instead of falling
 * through to the template picker. #chat-studio-thread is where the
 * message list + composer belong once the interview is built; until then
 * "Skip interview" is the only way through, and lands on the same template
 * picker "Start from a template" uses.
 */
export function chatStudioViewHtml(): string {
  return `
<div id="chat-studio-view" class="chat-studio-view" style="display:none">
  <header class="topbar topbar-home">
    ${brandHtml("brand-chat-studio", true)}
    <div class="toolbar">
      <button class="btn subtle" id="btn-chat-studio-back" type="button">Back</button>
    </div>
  </header>
  <main class="chat-studio-main">
    <div class="chat-studio-card">
      <div class="chat-studio-badge">New Project</div>
      <h2 class="chat-studio-title">Let's plan your video</h2>
      <p class="chat-studio-sub">The guided interview isn't built yet. Soon this will ask about your goal, length, scenes, and what footage you already have.</p>
      <div class="chat-studio-thread-placeholder" id="chat-studio-thread">
        <p>Project interview coming soon.</p>
      </div>
      <div class="chat-studio-actions">
        <button class="btn subtle" id="btn-chat-studio-skip" type="button">Skip interview — choose a template</button>
      </div>
    </div>
  </main>
</div>`;
}
