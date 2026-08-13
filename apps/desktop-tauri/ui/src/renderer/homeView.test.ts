import { describe, it, expect } from "vitest";
import { homeViewHtml, AI_SUGGESTIONS } from "./home";
import { brandHtml, LOGO_SRC } from "./brand";

describe("home hero", () => {
  it("leads with the product name instead of a greeting", () => {
    const html = homeViewHtml();

    expect(html).not.toContain("Welcome to");
  });

  it("colors Render and Flow separately so each word stands on its own", () => {
    const html = homeViewHtml();

    const render = html.match(/<span class="([^"]+)">Render<\/span>/);
    const flow = html.match(/<span class="([^"]+)">Flow<\/span>/);

    expect(render).not.toBeNull();
    expect(flow).not.toBeNull();
    expect(render![1]).not.toBe(flow![1]);
  });
});

describe("home topbar", () => {
  it("has no Dev Mode toggle", () => {
    const html = homeViewHtml();

    expect(html).not.toContain("Dev Mode");
    expect(html).not.toContain("btn-toggle-dev-mode");
  });

  it("shows the Deepiri logo top-left, ahead of the product name", () => {
    const html = homeViewHtml();

    const logoAt = html.indexOf(LOGO_SRC);
    expect(logoAt).toBeGreaterThan(-1);
    // Inside the brand block, which the topbar renders before the toolbar.
    expect(logoAt).toBeLessThan(html.indexOf("btn-toggle-theme-home"));
  });
});

describe("brand mark", () => {
  it("points at a swappable logo file rather than inlining artwork", () => {
    expect(brandHtml("brand-x")).toContain(`src="${LOGO_SRC}"`);
  });

  it("labels the logo for screen readers", () => {
    expect(brandHtml("brand-x")).toContain('alt="Deepiri"');
  });
});

describe("home prompt entry", () => {
  it("offers every starter prompt as a one-click chip", () => {
    const html = homeViewHtml();

    for (const suggestion of AI_SUGGESTIONS) {
      expect(html).toContain(`data-prompt="${suggestion}"`);
    }
  });

  it("gives the user a prompt box and a generate action", () => {
    const html = homeViewHtml();

    expect(html).toContain('id="home-prompt"');
    expect(html).toContain('id="btn-home-generate"');
  });

  it("keeps a separate way into the template flow", () => {
    expect(homeViewHtml()).toContain('id="btn-home-new-project"');
  });
});
