#!/usr/bin/env python3
"""Create a neutral blind-review package from SVG or PNG, without network calls.

Public files contain no region names or intended answers.  Private mapping keeps
source hashes, view IDs, offsets and random seeds for later unblinding.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile

from render_svg import parse_viewbox, png_size

FULL_QUESTION = """你从未见过这张图，也不知道作者想表达什么。只根据图像回答：
1. 图中各对象是什么，依据是什么？
2. 按顺序复述输入、结构/分子变化、跨区室作用、细胞命运和结局。
3. 逐条列出主要箭头/虚线/抑制线的起点、实际终点和含义。
4. 哪些内容指空、指歪、被遮挡、重复、看不清或必须靠常识补全？
不要替作者补答案，不确定就明确写不确定。"""
CROP_QUESTION = """这是一张没有上下文说明的局部科研图。只根据图像回答：
1. 看到的结构、分子、文字及升降；
2. 每条连线的实际起点、终点、方向及作用位置；
3. 能直接读出的局部因果过程；
4. 指空、指歪、遮挡、重复、文字难读或需要猜测之处。
裁切造成的正常画外线不要直接算作原图缺陷，也不要替作者补答案。"""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_image(path: Path):
    try:
        from PIL import Image
    except Exception as exc:
        raise RuntimeError("Pillow is required for blind-panel generation") from exc
    return Image.open(path).convert("RGB")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--views", type=Path)
    parser.add_argument("--scale", type=float)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--full-long-side", type=int, default=2200)
    parser.add_argument("--strip-metadata", action="store_true")
    args = parser.parse_args()
    try:
        source = args.input.resolve()
        out = args.out_dir.resolve()
        public, private = out / "public", out / "private"
        public.mkdir(parents=True, exist_ok=True)
        private.mkdir(parents=True, exist_ok=True)
        spec = json.loads(args.views.read_text(encoding="utf-8")) if args.views else {}
        with tempfile.TemporaryDirectory(prefix="sci-figure-blind-") as tmp:
            tmp_path = Path(tmp)
            if source.suffix.lower() == ".svg":
                vb = parse_viewbox(source)
                scale = args.scale if args.scale is not None else 3.0
                rendered = tmp_path / "full.png"
                metadata = tmp_path / "render.json"
                command = [sys.executable, str(Path(__file__).with_name("render_svg.py")), str(source),
                           "--output", str(rendered), "--scale", str(scale), "--metadata", str(metadata)]
                result = subprocess.run(command, capture_output=True, text=True)
                if result.returncode != 0:
                    raise RuntimeError(f"SVG render failed: {result.stderr or result.stdout}")
                shutil.copyfile(metadata, private / "render.json")
            else:
                scale = args.scale if args.scale is not None else 1.0
                with load_image(source) as probe:
                    vb = (0.0, 0.0, float(probe.width), float(probe.height))
                rendered = tmp_path / "full.png"
                with load_image(source) as im:
                    if scale != 1.0:
                        im = im.resize((round(im.width*scale), round(im.height*scale)))
                    im.save(rendered)
            with load_image(rendered) as full:
                sx, sy = full.width / vb[2], full.height / vb[3]
                preview = full.copy()
                preview.thumbnail((args.full_long_side, args.full_long_side))
                preview.save(public / "full.jpg", quality=90)
                mappings = []
                sets = spec.get("sets", [0])
                for set_index, set_spec in enumerate(sets):
                    if isinstance(set_spec, dict):
                        offset = float(set_spec.get("offset", 0))
                        set_name = set_spec.get("name", chr(65 + set_index))
                    else:
                        offset = float(set_spec)
                        set_name = chr(65 + set_index)
                    neutral_set = f"set_{set_name}"
                    set_dir = public / neutral_set
                    set_dir.mkdir(parents=True, exist_ok=True)
                    views = list(spec.get("views", []))
                    random.Random(args.seed + set_index).shuffle(views)
                    for panel_index, view in enumerate(views, 1):
                        box = view["box"]
                        x0, y0, x1, y1 = box
                        x0 += offset
                        x1 += offset
                        if x0 < vb[0] or y0 < vb[1] or x1 > vb[0]+vb[2] or y1 > vb[1]+vb[3] or x1 <= x0 or y1 <= y0:
                            raise RuntimeError(f"view outside coordinate space: set={set_name}, view={view.get('id')}, box={box}, offset={offset}")
                        crop_box = (round((x0-vb[0])*sx), round((y0-vb[1])*sy),
                                    round((x1-vb[0])*sx), round((y1-vb[1])*sy))
                        crop = full.crop(crop_box)
                        if crop.width < 1 or crop.height < 1:
                            raise RuntimeError(f"empty crop: {view.get('id')}")
                        relative = f"{neutral_set}/panel_{panel_index:02d}.png"
                        crop.save(public / relative)
                        mappings.append({"public_file": relative, "set": neutral_set,
                                         "view_id": view.get("id", f"view_{panel_index}"),
                                         "box": box, "offset": offset, "crop_pixels": list(crop.size)})
            if args.prompt_file:
                prompt_text = args.prompt_file.read_text(encoding="utf-8")
                (public / "questions.md").write_text(prompt_text, encoding="utf-8")
            else:
                (public / "questions.md").write_text(
                    "# 整图问题\n\n" + FULL_QUESTION + "\n\n# 局部图问题\n\n" + CROP_QUESTION + "\n",
                    encoding="utf-8")
            public_manifest = {"full": "full.jpg", "questions": "questions.md",
                               "panels": [m["public_file"] for m in mappings]}
            (public / "manifest.json").write_text(json.dumps(public_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            private_manifest = {
                "input": str(source), "input_sha256": sha256(source), "viewBox": vb,
                "coordinate_space": spec.get("coordinate_space", "viewBox" if source.suffix.lower() == ".svg" else "pixels"),
                "render_scale": scale, "seed": args.seed, "mapping": mappings,
            }
            (private / "mapping.json").write_text(json.dumps(private_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        result = {"ok": True, "public": str(public), "private": str(private),
                  "full_views": 1, "local_views": len(mappings), "total_views": 1+len(mappings),
                  "network_calls": 0}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
