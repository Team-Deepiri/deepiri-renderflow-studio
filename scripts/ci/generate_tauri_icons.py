#!/usr/bin/env python3
"""Generate a source app icon and Tauri icon set for CI releases."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "apps" / "desktop-tauri"
SOURCE_ICON = DESKTOP / "app-icon.png"
ICONS_DIR = DESKTOP / "src-tauri" / "icons"


def main() -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pillow"])
        from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGBA", (512, 512), (99, 102, 241, 255))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((48, 48, 464, 464), radius=64, fill=(30, 41, 59, 255))
    draw.text((170, 200), "RF", fill=(255, 255, 255, 255))
    SOURCE_ICON.parent.mkdir(parents=True, exist_ok=True)
    img.save(SOURCE_ICON)

    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        ["npm", "exec", "tauri", "--", "icon", str(SOURCE_ICON), "-o", str(ICONS_DIR)],
        cwd=DESKTOP,
    )
    print(f"Generated icons under {ICONS_DIR}")


if __name__ == "__main__":
    main()
