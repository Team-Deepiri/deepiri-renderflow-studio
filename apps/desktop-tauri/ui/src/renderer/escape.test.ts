import { describe, it, expect } from "vitest";
import { escapeHtml } from "./escape";

describe("escapeHtml", () => {
  it("defuses markup in names that came from a user prompt", () => {
    expect(escapeHtml('<img src=x onerror="alert(1)">')).toBe(
      "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;",
    );
  });

  it("keeps a value from breaking out of an attribute", () => {
    expect(escapeHtml('" onmouseover="steal()')).not.toContain('"');
  });

  it("escapes ampersands so entities are not double-decoded", () => {
    expect(escapeHtml("Tom & Jerry")).toBe("Tom &amp; Jerry");
  });

  it("leaves ordinary text alone", () => {
    expect(escapeHtml("A neon-lit city street")).toBe("A neon-lit city street");
  });
});
