import type { Asset } from "../types";

export type AssetCallbacks = {
  /** Single click — preview the asset in the program monitor. */
  onAssetPreview?: (asset: Asset) => void;
};

/** Re-renders the asset list into `root`. */
export function renderAssetList(
  assets: Asset[],
  root: HTMLElement,
  callbacks: AssetCallbacks
): void {
  root.innerHTML = "";
  for (const asset of assets) {
    const meta = asset.meta_jsonb ?? {};
    const name = (meta as Record<string, unknown>)["name"] as string | undefined
      ?? asset.uri.split("/").pop()
      ?? asset.uri;

    const li = document.createElement("li");
    li.className = "asset-item";

    const badgeClass =
      asset.kind === "video"
        ? "badge-video"
        : asset.kind === "audio"
        ? "badge-audio"
        : "badge-image";

    const w = (meta as Record<string, unknown>)["width"] as number | undefined;
    const h = (meta as Record<string, unknown>)["height"] as number | undefined;
    const fpsVal = (meta as Record<string, unknown>)["fps"] as number | undefined;
    const proxyStatus = meta.proxy_status ?? "unavailable";

    const resMeta = w && h ? `${w}×${h}` : "";
    const durMeta = asset.duration_ms != null ? fmtDuration(asset.duration_ms) : "";
    const fpsMeta = fpsVal != null ? `${fpsVal.toFixed(2)} fps` : "";
    const proxyLabel =
      proxyStatus === "pending"
        ? "⏳ proxy"
        : proxyStatus === "ready"
        ? "✓ proxy"
        : proxyStatus === "failed"
        ? "✗ proxy"
        : "";
    const proxyClass =
      proxyStatus === "ready"
        ? "proxy-ready"
        : proxyStatus === "failed"
        ? "proxy-failed"
        : "proxy-pending";

    li.innerHTML = `
      <div class="asset-item-name" title="${asset.uri}">${name}</div>
      <div class="asset-item-meta">
        <span class="asset-badge ${badgeClass}">${asset.kind}</span>
        ${durMeta ? `<span>${durMeta}</span>` : ""}
        ${resMeta ? `<span>${resMeta}</span>` : ""}
        ${fpsMeta ? `<span>${fpsMeta}</span>` : ""}
        ${proxyLabel ? `<span class="${proxyClass}">${proxyLabel}</span>` : ""}
      </div>
    `;

    li.title = "Click to preview";
    li.addEventListener("click", () => callbacks.onAssetPreview?.(asset));
    root.appendChild(li);
  }
}

/** Formats a duration in milliseconds as M:SS or H:MM:SS. */
export function fmtDuration(ms: number | null): string {
  if (ms == null) return "";
  const s = Math.floor(ms / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) {
    return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  }
  return `${m}:${String(sec).padStart(2, "0")}`;
}
