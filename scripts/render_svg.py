#!/usr/bin/env python3
"""Render an SVG with an explicit viewBox/region and auditable metadata.

Offline, account-free and project-agnostic.  Chromium is preferred when present;
CairoSVG is an optional fallback.  No fixed browser path is required.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


class RenderError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise RenderError(f"not a valid PNG: {path}")
    return struct.unpack(">II", header[16:24])


def parse_viewbox(source: Path) -> tuple[float, float, float, float]:
    try:
        root = ET.parse(source).getroot()
    except Exception as exc:
        raise RenderError(f"cannot parse SVG: {exc}") from exc
    viewbox = root.attrib.get("viewBox")
    if viewbox:
        values = [float(v) for v in re.split(r"[ ,]+", viewbox.strip()) if v]
        if len(values) != 4 or values[2] <= 0 or values[3] <= 0:
            raise RenderError(f"invalid viewBox: {viewbox}")
        return tuple(values)
    def number(name: str) -> float:
        value = root.attrib.get(name, "")
        match = re.fullmatch(r"\s*([0-9.]+)\s*(?:px)?\s*", value)
        if not match:
            raise RenderError("SVG needs viewBox or numeric px width/height")
        return float(match.group(1))
    return (0.0, 0.0, number("width"), number("height"))


def replace_root_attrs(svg: str, width: float, height: float, viewbox: tuple[float, ...]) -> str:
    match = re.search(r"<svg\b[^>]*>", svg, flags=re.IGNORECASE)
    if not match:
        raise RenderError("opening <svg> tag not found")
    root = match.group(0)
    root = re.sub(r"\s+width=\"[^\"]*\"", "", root, flags=re.IGNORECASE)
    root = re.sub(r"\s+height=\"[^\"]*\"", "", root, flags=re.IGNORECASE)
    root = re.sub(r"\s+viewBox=\"[^\"]*\"", "", root, flags=re.IGNORECASE)
    vb = " ".join(f"{v:g}" for v in viewbox)
    replacement = root[:-1] + f' width="{width:g}" height="{height:g}" viewBox="{vb}">'
    return svg[:match.start()] + replacement + svg[match.end():]


def browser_candidates() -> list[str]:
    candidates = []
    if os.environ.get("CHROME_BIN"):
        candidates.append(os.environ["CHROME_BIN"])
    for name in ("msedge", "chrome", "chromium", "chromium-browser", "google-chrome"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    if sys.platform == "win32":
        candidates.extend([
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ])
    elif sys.platform == "darwin":
        candidates.extend([
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ])
    else:
        candidates.extend(["/usr/bin/chromium", "/usr/bin/google-chrome"])
    return list(dict.fromkeys(candidates))


def find_browser(explicit: str | None = None) -> str:
    if explicit:
        if Path(explicit).is_file():
            return explicit
        found = shutil.which(explicit)
        if found:
            return found
        raise RenderError(f"browser not found: {explicit}")
    for candidate in browser_candidates():
        if Path(candidate).is_file():
            return candidate
    raise RenderError("no Chromium browser found; use --backend cairosvg or --executable")


def browser_version(executable: str) -> str:
    try:
        result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=10)
        return (result.stdout or result.stderr).strip()
    except Exception:
        return "unknown"


def render_chromium(source: Path, output: Path, svg_text: str, region: tuple[float, ...],
                    css_size: tuple[int, int], scale: float, executable: str | None,
                    timeout: int) -> dict:
    browser = find_browser(executable)
    with tempfile.TemporaryDirectory(prefix="sci-figure-render-") as tmp:
        tmp_path = Path(tmp)
        shot = tmp_path / "figure.png"
        if region is None:
            uri = source.resolve().as_uri()
        else:
            base = source.resolve().parent.as_uri() + "/"
            html = ("<!doctype html><html><head><meta charset=\"utf-8\">"
                    f"<base href=\"{base}\"><style>html,body{{margin:0;padding:0;overflow:hidden}}</style>"
                    f"</head><body>{svg_text}</body></html>")
            page = tmp_path / "region.html"
            page.write_text(html, encoding="utf-8")
            uri = page.as_uri()
        command = [
            browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
            "--allow-file-access-from-files", f"--user-data-dir={tmp_path / 'profile'}",
            f"--force-device-scale-factor={scale:g}", f"--window-size={css_size[0]},{css_size[1]}",
            f"--screenshot={shot}", uri,
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        if not shot.is_file() or shot.stat().st_size == 0:
            detail = (result.stderr or result.stdout or "no PNG produced")[-1200:]
            raise RenderError(f"Chromium render failed: {detail}")
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(shot, output)
    return {"backend": "chromium", "backend_version": browser_version(browser)}


def render_cairosvg(output: Path, svg_text: str, size: tuple[int, int]) -> dict:
    try:
        import cairosvg  # type: ignore
    except Exception as exc:
        raise RenderError("CairoSVG is unavailable; install it or select Chromium") from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2png(bytestring=svg_text.encode("utf-8"), write_to=str(output),
                     output_width=size[0], output_height=size[1])
    return {"backend": "cairosvg", "backend_version": getattr(cairosvg, "__version__", "unknown")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--backend", choices=("auto", "chromium", "cairosvg"), default="auto")
    parser.add_argument("--executable")
    size_group = parser.add_mutually_exclusive_group()
    size_group.add_argument("--scale", type=float)
    size_group.add_argument("--width", type=int)
    size_group.add_argument("--height", type=int)
    size_group.add_argument("--long-side", type=int)
    parser.add_argument("--region", help="x0,y0,x1,y1 in SVG viewBox coordinates")
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    try:
        source = args.input.resolve()
        output = args.output.resolve()
        if not source.is_file():
            raise RenderError(f"input not found: {source}")
        vb = parse_viewbox(source)
        if args.region:
            values = [float(v) for v in args.region.split(",")]
            if len(values) != 4:
                raise RenderError("--region requires four comma-separated numbers")
            x0, y0, x1, y1 = values
            if x0 < vb[0] or y0 < vb[1] or x1 > vb[0]+vb[2] or y1 > vb[1]+vb[3] or x1 <= x0 or y1 <= y0:
                raise RenderError(f"region outside viewBox {vb}: {values}")
            region = (x0, y0, x1, y1)
        else:
            region = None
        rw, rh = (region[2]-region[0], region[3]-region[1]) if region else (vb[2], vb[3])
        if args.width:
            scale = args.width / rw
        elif args.height:
            scale = args.height / rh
        elif args.long_side:
            scale = args.long_side / max(rw, rh)
        else:
            scale = args.scale if args.scale is not None else 1.0
        if scale <= 0:
            raise RenderError("scale must be positive")
        output_size = (max(1, round(rw*scale)), max(1, round(rh*scale)))
        css_size = (max(1, round(rw)), max(1, round(rh)))
        svg_text = source.read_text(encoding="utf-8")
        if region:
            svg_text = replace_root_attrs(svg_text, rw, rh, region)
        backend = args.backend
        if backend == "auto":
            try:
                find_browser(args.executable)
                backend = "chromium"
            except RenderError:
                backend = "cairosvg"
        if backend == "chromium":
            meta = render_chromium(source, output, svg_text, region, css_size, scale,
                                   args.executable, args.timeout)
        else:
            meta = render_cairosvg(output, svg_text, output_size)
        actual_size = png_size(output)
        result = {
            "ok": True, "input": str(source), "input_sha256": sha256(source),
            "output": str(output), "output_sha256": sha256(output),
            "viewBox": vb, "region": region, "scale": scale,
            "requested_pixels": output_size, "actual_pixels": actual_size,
            **meta,
        }
        if actual_size != output_size:
            result["warning"] = f"browser pixel rounding: requested {output_size}, got {actual_size}"
        if args.metadata:
            args.metadata.parent.mkdir(parents=True, exist_ok=True)
            args.metadata.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
