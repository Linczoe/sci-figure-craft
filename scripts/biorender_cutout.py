#!/usr/bin/env python3
"""BioRender 画布截图抠图：从单图标 3 倍截图的中心窗口提取 RGBA PNG。

配合 biorender_capture_run.ps1 使用：每个图标放在画布中心 (cx, cy) 后截图，
本脚本在中心窗口内取非白区域，闭合填洞、去噪点，并按 alpha 反解被白底
稀释的边缘颜色（去白边），输出带透明通道的 PNG。

用法：
  python biorender_cutout.py --raw-dir "<raw>" --out-dir "<素材库>" [--sheet "<对照图.png>"]
  python biorender_cutout.py --raw-dir "<raw>" --out-dir "<素材库>" --names mouse,tablet_white

坐标换算：仿真截图时 deviceScaleFactor 被直接设为 scale，故 K=scale（不是屏幕 DPR×scale）。
依赖：Pillow、numpy、scipy。
"""
from __future__ import annotations

import argparse
import os
import sys


def extract(path, k, cx, cy, half):
    import numpy as np
    from PIL import Image
    from scipy import ndimage

    im = Image.open(path).convert('RGB')
    a = np.array(im)
    ccx, ccy = cx * k, cy * k
    hh = int(half * k)
    x0, y0 = int(ccx - hh), int(ccy - hh)
    sub = a[y0:y0 + 2 * hh, x0:x0 + 2 * hh].astype(np.float32)
    mask = sub.min(axis=2) < 246                      # 非白
    mask = ndimage.binary_closing(mask, iterations=2)  # 闭合细缝，便于填洞
    lab, n = ndimage.label(mask, structure=np.ones((3, 3)))
    if n == 0:
        return None
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    keep = np.isin(lab, [i + 1 for i, s in enumerate(sizes) if s >= 40])  # 去噪点（<40 px²）
    keep = ndimage.binary_fill_holes(keep)
    keep = ndimage.binary_dilation(keep, iterations=1)
    alpha = ndimage.gaussian_filter(keep.astype(np.float32), 0.9)
    # 去白边：按 alpha 反解被白底稀释的边缘颜色
    af = np.clip(alpha, 0.05, 1.0)[..., None]
    rgb = np.clip((sub - (1.0 - af) * 255.0) / af, 0, 255)
    ys, xs = np.where(alpha > 0.02)
    if len(ys) == 0:
        return None
    y1, y2, x1, x2 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    rgba = np.dstack([rgb[y1:y2, x1:x2], (alpha[y1:y2, x1:x2] * 255)]).astype(np.uint8)
    return Image.fromarray(rgba, 'RGBA')


def make_sheet(items, out):
    from PIL import Image, ImageDraw, ImageFont

    tile, pad, cols = 230, 10, 7
    rows = (len(items) + cols - 1) // cols
    sh = Image.new('RGB', (cols * (tile + pad), rows * (tile + pad + 24)), (226, 234, 242))
    try:
        f = ImageFont.truetype('arialbd.ttf', 15)
    except OSError:
        f = ImageFont.load_default()
    d = ImageDraw.Draw(sh)
    for i, (name, im) in enumerate(items):
        x = (i % cols) * (tile + pad)
        y = (i // cols) * (tile + pad + 24)
        t = im.copy()
        t.thumbnail((tile - 10, tile - 10), Image.LANCZOS)
        sh.paste(t, (x + 5 + (tile - 10 - t.width) // 2, y + 24 + (tile - 10 - t.height) // 2), t)
        d.text((x + 4, y + 4), f'{name} {im.width}x{im.height}', fill=(30, 30, 30), font=f)
    sh.save(out)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--raw-dir', required=True, help='原始截图目录（每图标一张 <name>.png）')
    p.add_argument('--out-dir', required=True, help='RGBA 素材输出目录')
    p.add_argument('--names', default='', help='只处理这些名字（逗号分隔）；默认处理 raw-dir 全部非 _ 开头 PNG')
    p.add_argument('--scale', type=float, default=3.0, help='截图时的 deviceScaleFactor，默认 3')
    p.add_argument('--cx', type=float, default=762, help='放置图标的画布中心 CSS x，默认 762')
    p.add_argument('--cy', type=float, default=330, help='放置图标的画布中心 CSS y，默认 330')
    p.add_argument('--half', type=float, default=118, help='中心窗口半径（CSS px），默认 118')
    p.add_argument('--sheet', default='', help='可选：输出一张素材对照图到该路径')
    args = p.parse_args()

    try:
        import numpy  # noqa: F401
        import scipy  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError as exc:
        print(f'缺少依赖：{exc.name}。请安装 Pillow、numpy、scipy 后重试。', file=sys.stderr)
        return 2

    os.makedirs(args.out_dir, exist_ok=True)
    if args.names:
        names = [n.strip() for n in args.names.split(',') if n.strip()]
    else:
        names = sorted(f[:-4] for f in os.listdir(args.raw_dir)
                       if f.endswith('.png') and not f.startswith('_'))
    items = []
    for n in names:
        path = os.path.join(args.raw_dir, n + '.png')
        if not os.path.exists(path):
            print('MISSING', n)
            continue
        im = extract(path, args.scale, args.cx, args.cy, args.half)
        if im is None:
            print('EMPTY', n)
            continue
        im.save(os.path.join(args.out_dir, n + '.png'))
        print(f'OK {n} {im.width}x{im.height}')
        items.append((n, im))
    if args.sheet and items:
        print('sheet', make_sheet(items, args.sheet))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
