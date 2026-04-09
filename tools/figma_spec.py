"""
tools/figma_spec.py

Fetches a Figma file via REST API and extracts a design spec:
  - Color styles
  - Typography styles
  - Frame names and dimensions
  - Component names

Usage:
  python tools/figma_spec.py
  python tools/figma_spec.py --output design-spec.json
"""

import argparse
import json
import os
import sys
from dotenv import load_dotenv
import urllib.request
import urllib.error

load_dotenv()

FIGMA_TOKEN = os.getenv("FIGMA_TOKEN")
FILE_KEY    = "AKY9gbLVORYKigCUNyNBZU"
BASE_URL    = "https://api.figma.com/v1"


def fetch(path: str) -> dict:
    url     = f"{BASE_URL}{path}"
    request = urllib.request.Request(url, headers={"X-Figma-Token": FIGMA_TOKEN})
    try:
        with urllib.request.urlopen(request) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"HTTP {e.code} — {e.reason}", file=sys.stderr)
        print(body, file=sys.stderr)
        sys.exit(1)


def extract_colors(styles: dict, style_meta: dict) -> dict:
    colors = {}
    for node_id, style in style_meta.items():
        if style.get("style_type") == "FILL":
            colors[style["name"]] = {"node_id": node_id, "description": style.get("description", "")}
    return colors


def extract_frames(node: dict, frames: list, depth: int = 0) -> None:
    if node.get("type") in ("FRAME", "COMPONENT", "COMPONENT_SET"):
        frames.append({
            "name":   node.get("name"),
            "type":   node.get("type"),
            "id":     node.get("id"),
            "width":  node.get("absoluteBoundingBox", {}).get("width"),
            "height": node.get("absoluteBoundingBox", {}).get("height"),
            "depth":  depth,
        })
    for child in node.get("children", []):
        extract_frames(child, frames, depth + 1)


def extract_text_styles(node: dict, styles: list) -> None:
    if node.get("type") == "TEXT":
        style = node.get("style", {})
        styles.append({
            "name":        node.get("name"),
            "fontFamily":  style.get("fontFamily"),
            "fontSize":    style.get("fontSize"),
            "fontWeight":  style.get("fontWeight"),
            "lineHeight":  style.get("lineHeightPx"),
            "letterSpacing": style.get("letterSpacing"),
        })
    for child in node.get("children", []):
        extract_text_styles(child, styles)


def extract_fills(node: dict, fills: list, depth: int = 0) -> None:
    if depth > 3:
        return
    name  = node.get("name", "")
    raw   = node.get("fills", [])
    for fill in raw:
        if fill.get("type") == "SOLID":
            c = fill.get("color", {})
            fills.append({
                "element": name,
                "hex": "#{:02X}{:02X}{:02X}".format(
                    int(c.get("r", 0) * 255),
                    int(c.get("g", 0) * 255),
                    int(c.get("b", 0) * 255),
                ),
                "opacity": round(fill.get("opacity", 1.0), 2),
            })
    for child in node.get("children", []):
        extract_fills(child, fills, depth + 1)


def main():
    parser = argparse.ArgumentParser(description="Extract Figma design spec")
    parser.add_argument("--output", default="", help="Save JSON to this file path")
    args = parser.parse_args()

    if not FIGMA_TOKEN:
        print("FIGMA_TOKEN not set in .env", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching Figma file: {FILE_KEY}...")
    data = fetch(f"/files/{FILE_KEY}")

    doc    = data.get("document", {})
    styles = data.get("styles", {})

    # ── Extract frames (screens + components)
    frames: list = []
    for page in doc.get("children", []):
        print(f"\nPage: {page['name']}")
        extract_frames(page, frames)

    top_frames = [f for f in frames if f["depth"] <= 1]

    # ── Extract text styles
    text_styles: list = []
    for page in doc.get("children", []):
        extract_text_styles(page, text_styles)
    # Deduplicate by fontSize+fontFamily
    seen = set()
    unique_text = []
    for s in text_styles:
        key = (s["fontFamily"], s["fontSize"], s["fontWeight"])
        if key not in seen and s["fontFamily"]:
            seen.add(key)
            unique_text.append(s)

    # ── Extract fill colors
    fills: list = []
    for page in doc.get("children", []):
        extract_fills(page, fills)
    # Deduplicate hex values
    unique_colors = list({f["hex"]: f for f in fills}.values())

    # ── Build spec
    spec = {
        "file_key": FILE_KEY,
        "file_name": data.get("name"),
        "last_modified": data.get("lastModified"),
        "screens": top_frames,
        "colors": unique_colors,
        "typography": unique_text,
        "style_count": len(styles),
    }

    output = json.dumps(spec, indent=2)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"\nSpec saved to {args.output}")
    else:
        print("\n" + output)


if __name__ == "__main__":
    main()
