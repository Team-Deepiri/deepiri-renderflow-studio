import { describe, it, expect, afterEach, vi } from "vitest";
import { orchestratorDeleteProject } from "./backendApi";

/** Stands in for fetch, returning one scripted response. */
function respondWith(init: { ok: boolean; status: number; body: unknown }) {
  const fetchMock = vi.fn(async () => ({
    ok: init.ok,
    status: init.status,
    json: async () => {
      if (typeof init.body !== "object") throw new SyntaxError("not JSON");
      return init.body;
    },
    text: async () => String(init.body),
  }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("orchestratorDeleteProject", () => {
  it("resolves when the server confirms the delete", async () => {
    respondWith({ ok: true, status: 200, body: { status: "deleted" } });

    await expect(orchestratorDeleteProject("proj-1")).resolves.toEqual({
      status: "deleted",
    });
  });

  it("throws when the server rejects the delete", async () => {
    // A silent resolve here is what made the Delete button look dead: the
    // caller removed the card locally while the project still existed.
    respondWith({ ok: false, status: 500, body: "Internal Server Error" });

    await expect(orchestratorDeleteProject("proj-1")).rejects.toThrow(
      /Internal Server Error/,
    );
  });

  it("throws on a missing project rather than reporting success", async () => {
    respondWith({ ok: false, status: 404, body: "project not found" });

    await expect(orchestratorDeleteProject("gone")).rejects.toThrow(
      /project not found/,
    );
  });
});
