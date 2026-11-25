#!/usr/bin/env python3
"""Audit SVG structure, declared semantics and real connector endpoints.

No network, credentials or project constants.  Scientific correctness is outside
this tool's scope: it verifies IDs, references, geometry and declarations only.
"""
from __future__ import annotations

import argparse
import base64
import fnmatch
import hashlib
import io
import json
import math
from collections import Counter
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

NUM = r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?"
TOKEN = re.compile(r"[MLHVCSQTAZmlhvcsqtaz]|" + NUM)
CJK = re.compile(r"[\u3400-\u9fff]")


class AuditError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def local_name(el) -> str:
    return el.tag.rsplit("}", 1)[-1]


def mat_mul(a, b):
    return (
        a[0]*b[0]+a[2]*b[1], a[1]*b[1]+a[3]*b[1],
        a[0]*b[2]+a[2]*b[3], a[1]*b[2]+a[3]*b[3],
        a[0]*b[4]+a[2]*b[5]+a[4], a[1]*b[4]+a[3]*b[5]+a[5],
    )


def transforms(text: str):
    matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for name, raw in re.findall(r"(matrix|translate|scale|rotate)\s*\(([^)]*)\)", text or ""):
        values = [float(v) for v in re.findall(NUM, raw)]
        if name == "matrix" and len(values) == 6:
            new = tuple(values)
        elif name == "translate":
            tx, ty = values[0], values[1] if len(values) > 1 else 0.0
            new = (1, 0, 0, 1, tx, ty)
        elif name == "scale":
            sx, sy = values[0], values[1] if len(values) > 1 else values[0]
            new = (sx, 0, 0, sy, 0, 0)
        elif name == "rotate":
            angle = math.radians(values[0])
            c, s = math.cos(angle), math.sin(angle)
            if len(values) >= 3:
                cx, cy = values[1], values[2]
                new = mat_mul(mat_mul((1,0,0,1,cx,cy), (c,s,-s,c,0,0)), (1,0,0,1,-cx,-cy))
            else:
                new = (c, s, -s, c, 0, 0)
        else:
            continue
        matrix = mat_mul(matrix, new)
    return matrix


def apply(point, matrix):
    x, y = point
    a, b, c, d, e, f = matrix
    return (a*x+c*y+e, b*x+d*y+f)


def full_transform(el, parents):
    chain = []
    current = el
    while current in parents:
        current = parents[current]
        chain.append(current)
    matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for ancestor in reversed(chain):
        matrix = mat_mul(matrix, transforms(ancestor.attrib.get("transform", "")))
    return matrix


def bbox_transform(box, matrix):
    points = [apply((box[0],box[1]),matrix), apply((box[2],box[1]),matrix),
              apply((box[2],box[3]),matrix), apply((box[0],box[3]),matrix)]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def text_bbox(el, font_regular=None, font_bold=None) -> tuple[float, float, float, float]:
    x, y = float(el.attrib.get("x", 0)), float(el.attrib.get("y", 0))
    size = float(el.attrib.get("font-size", 16))
    value = "".join(el.itertext())
    bold = el.attrib.get("font-weight") in ("600", "700", "bold")
    try:
        from PIL import ImageFont
        if bold and font_bold:
            font = ImageFont.truetype(font_bold, max(1, round(size*6)))
        elif font_regular:
            font = ImageFont.truetype(font_regular, max(1, round(size*6)))
        else:
            candidates = [r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
                          "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
            font = None
            for candidate in candidates:
                if Path(candidate).is_file():
                    font = ImageFont.truetype(candidate, max(1, round(size*6)))
                    break
            if font is None:
                raise ValueError("no font")
        width = font.getlength(value) / 6
    except Exception:
        width = sum(0.60 if ord(ch) < 128 else 1.0 for ch in value) * size
    anchor = el.attrib.get("text-anchor", "start")
    x0 = x-width/2 if anchor == "middle" else (x-width if anchor == "end" else x)
    return (x0, y-size, x0+width, y+size*0.30)


def element_bbox(el, parents, font_regular=None, font_bold=None):
    if el.attrib.get("data-bbox"):
        values = [float(v) for v in el.attrib["data-bbox"].split(",")]
        box = tuple(values)
    else:
        tag = local_name(el)
        if tag == "text":
            box = text_bbox(el, font_regular, font_bold)
        elif tag == "circle":
            cx, cy, r = (float(el.attrib[k]) for k in ("cx", "cy", "r"))
            box = (cx-r, cy-r, cx+r, cy+r)
        elif tag == "ellipse":
            cx, cy, rx, ry = (float(el.attrib[k]) for k in ("cx", "cy", "rx", "ry"))
            box = (cx-rx, cy-ry, cx+rx, cy+ry)
        elif tag in ("rect", "image"):
            x, y = (float(el.attrib.get(k, 0)) for k in ("x", "y"))
            w, h = float(el.attrib["width"]), float(el.attrib["height"])
            box = (x, y, x+w, y+h)
        elif tag == "polygon":
            values = [float(v) for v in re.findall(NUM, el.attrib.get("points", ""))]
            xs, ys = values[0::2], values[1::2]
            box = (min(xs), min(ys), max(xs), max(ys))
        elif tag == "line":
            x1, y1, x2, y2 = (float(el.attrib[k]) for k in ("x1", "y1", "x2", "y2"))
            box = (min(x1,x2), min(y1,y2), max(x1,x2), max(y1,y2))
        else:
            return None
    matrix = mat_mul(full_transform(el, parents), transforms(el.attrib.get("transform", "")))
    return bbox_transform(box, matrix)


def path_endpoints(d: str):
    tokens = TOKEN.findall(d)
    i = 0
    command = None
    current = start = end = None
    while i < len(tokens):
        if tokens[i].isalpha():
            command = tokens[i]
            i += 1
            if command in ("Z", "z"):
                if start is not None:
                    current = start
                    end = start
            continue
        if command is None:
            raise AuditError("path does not start with a command")
        relative = command.islower()
        op = command.upper()
        counts = {"M":2,"L":2,"H":1,"V":1,"C":6,"S":4,"Q":4,"T":2,"A":7}
        if op not in counts:
            raise AuditError(f"unsupported path command {command}")
        count = counts[op]
        if i+count > len(tokens):
            raise AuditError("truncated path command")
        values = [float(v) for v in tokens[i:i+count]]
        i += count
        if op == "H":
            nx = current[0]+values[0] if relative else values[0]
            current = (nx, current[1])
        elif op == "V":
            ny = current[1]+values[0] if relative else values[0]
            current = (current[0], ny)
        elif op in ("M", "L", "T"):
            x, y = values
            current = (current[0]+x, current[1]+y) if relative else (x, y)
            if op == "M" and start is None:
                start = current
        elif op in ("C", "S", "Q"):
            x, y = values[-2:]
            current = (current[0]+x, current[1]+y) if relative else (x, y)
        elif op == "A":
            x, y = values[-2:]
            current = (current[0]+x, current[1]+y) if relative else (x, y)
        end = current
        if op == "M":
            command = "l" if relative else "L"
    if start is None or end is None:
        raise AuditError("path has no endpoints")
    return start, end


def connector_endpoints(el, parents):
    candidates = [child for child in el.iter() if local_name(child) in ("path", "line")]
    if not candidates:
        raise AuditError("connector has no path/line")
    shape = candidates[0]
    if local_name(shape) == "line":
        start = (float(shape.attrib["x1"]), float(shape.attrib["y1"]))
        end = (float(shape.attrib["x2"]), float(shape.attrib["y2"]))
    else:
        start, end = path_endpoints(shape.attrib.get("d", ""))
    matrix = full_transform(shape, parents)
    return apply(start, matrix), apply(end, matrix)


def distance(point, box) -> float:
    x, y = point
    x0, y0, x1, y1 = box
    return math.hypot(max(x0-x, 0, x-x1), max(y0-y, 0, y-y1))


def image_href(el):
    for key, value in el.attrib.items():
        if key.endswith("href"):
            return value
    return None


def alpha_target_status(target, point, svg_dir: Path):
    """Best-effort visible-alpha check for raster targets, including rotation."""
    images = [el for el in target.iter() if local_name(el) == "image"]
    if not images:
        return "not_applicable"
    try:
        from PIL import Image
    except Exception:
        return "not_assessed:no_Pillow"
    el = images[0]
    href = image_href(el)
    try:
        if href and href.startswith("data:image"):
            raw = base64.b64decode(href.split(",", 1)[1])
            im = Image.open(io.BytesIO(raw)).convert("RGBA")
        elif href:
            im = Image.open(svg_dir / href).convert("RGBA")
        else:
            return "not_assessed:no_href"
        x, y = float(el.attrib.get("x", 0)), float(el.attrib.get("y", 0))
        w, h = float(el.attrib["width"]), float(el.attrib["height"])
        px, py = point
        rotate = re.search(r"rotate\(\s*([-0-9.]+)(?:\s+([-0-9.]+)\s+([-0-9.]+))?", el.attrib.get("transform", ""))
        if rotate:
            angle = math.radians(-float(rotate.group(1)))
            cx = float(rotate.group(2)) if rotate.group(2) else x+w/2
            cy = float(rotate.group(3)) if rotate.group(3) else y+h/2
            dx, dy = px-cx, py-cy
            px, py = cx+dx*math.cos(angle)-dy*math.sin(angle), cy+dx*math.sin(angle)+dy*math.cos(angle)
        sx, sy = (px-x)/w*im.width, (py-y)/h*im.height
        if sx < -0.5 or sy < -0.5 or sx > im.width+0.5 or sy > im.height+0.5:
            return "outside"
        # SVG outlines commonly terminate exactly on the raster edge; include that boundary.
        sx = min(max(sx, 0.0), im.width-1)
        sy = min(max(sy, 0.0), im.height-1)
        radius = 3
        alpha = im.getchannel("A")
        for yy in range(max(0, int(sy)-radius), min(im.height, int(sy)+radius+1)):
            for xx in range(max(0, int(sx)-radius), min(im.width, int(sx)+radius+1)):
                if alpha.getpixel((xx, yy)) > 16:
                    return "visible"
        return "transparent"
    except Exception as exc:
        return f"not_assessed:{type(exc).__name__}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--rendered", type=Path)
    parser.add_argument("--tolerance", type=float, default=12.0)
    parser.add_argument("--tolerance-mode", choices=("absolute", "canvas-ratio", "target-ratio"), default="absolute")
    parser.add_argument("--font-regular")
    parser.add_argument("--font-bold")
    parser.add_argument("--text-policy", choices=("any", "no-cjk"), default="any")
    parser.add_argument("--check-all-sources", action="store_true")
    parser.add_argument("--fail-on", choices=("error", "warning", "never"), default="error")
    args = parser.parse_args()
    errors, warnings, checks = [], [], []
    try:
        source = args.input.resolve()
        spec = json.loads(args.spec.read_text(encoding="utf-8")) if args.spec else {}
        root = ET.parse(source).getroot()
        parents = {child: parent for parent in root.iter() for child in parent}
        all_elements = list(root.iter())
        order = {id(el): idx for idx, el in enumerate(all_elements)}
        elements_list = [el for el in all_elements if "id" in el.attrib]
        elements = {el.attrib["id"]: el for el in elements_list}
        ids = [el.attrib["id"] for el in elements_list]
        for eid, count in Counter(ids).items():
            if count > 1:
                errors.append({"code": "duplicate-id", "id": eid, "count": count})
        ignore = spec.get("ignore", [])
        text_policy = spec.get("text_policy", args.text_policy)
        for el in all_elements:
            if local_name(el) == "text":
                value = "".join(el.itertext())
                if text_policy == "no-cjk" and CJK.search(value):
                    errors.append({"code": "cjk-text", "id": el.attrib.get("id"), "text": value})
        edge_specs = {entry["id"]: entry for entry in spec.get("edges", [])}
        for required in spec.get("required_edges", []):
            if required not in elements:
                errors.append({"code": "missing-required-edge", "id": required})
        for region in spec.get("regions", []):
            allowed = tuple(region["bbox"])
            pattern = re.compile(region["selector"])
            for eid, el in elements.items():
                if pattern.search(eid):
                    box = element_bbox(el, parents, args.font_regular, args.font_bold)
                    if box and (box[0] < allowed[0] or box[1] < allowed[1] or box[2] > allowed[2] or box[3] > allowed[3]):
                        errors.append({"code": "outside-region", "region": region["name"], "id": eid, "bbox": box})
        connectors = [el for el in all_elements if el.attrib.get("data-kind") == "connector"]
        seen_edges = set()
        for connector in connectors:
            cid = connector.attrib.get("id")
            if not cid or any(fnmatch.fnmatch(cid, pattern) for pattern in ignore) or connector.attrib.get("data-audit") == "ignore":
                continue
            edge_spec = edge_specs.get(cid, {})
            source_id = edge_spec.get("source") or connector.attrib.get("data-source-id")
            target_id = edge_spec.get("target") or connector.attrib.get("data-target-id")
            # Legacy natural-language source/target attributes are not treated as IDs.
            if not target_id:
                warnings.append({"code": "unregistered-connector", "id": cid})
                continue
            declared_relation = connector.attrib.get("data-relation") or connector.attrib.get("data-connector")
            expected_relation = edge_spec.get("relation")
            if expected_relation and declared_relation and declared_relation != expected_relation:
                errors.append({"code": "relation-mismatch", "id": cid,
                               "expected": expected_relation, "actual": declared_relation})
            elif expected_relation and not declared_relation:
                warnings.append({"code": "relation-not-declared", "id": cid, "expected": expected_relation})
            relation = expected_relation or declared_relation
            semantic_source = source_id or connector.attrib.get("data-source") or connector.attrib.get("data-source-id")
            signature = (semantic_source, target_id, relation, connector.attrib.get("data-panel", ""))
            if signature in seen_edges:
                errors.append({"code": "duplicate-semantic-edge", "id": cid, "signature": signature})
            seen_edges.add(signature)
            target = elements.get(target_id)
            if target is None:
                errors.append({"code": "missing-target", "id": cid, "target": target_id})
                continue
            try:
                start, end = connector_endpoints(connector, parents)
            except Exception as exc:
                errors.append({"code": "path-parse", "id": cid, "error": str(exc)})
                continue
            target_box = element_bbox(target, parents, args.font_regular, args.font_bold)
            if target_box is None:
                warnings.append({"code": "target-bbox-unavailable", "id": cid, "target": target_id})
                continue
            tolerance = args.tolerance
            if args.tolerance_mode == "target-ratio":
                tolerance = args.tolerance * max(target_box[2]-target_box[0], target_box[3]-target_box[1]) / 100
            target_distance = distance(end, target_box)
            record = {"id": cid, "target": target_id, "endpoint": end,
                      "target_bbox": target_box, "distance": round(target_distance, 3)}
            alpha = alpha_target_status(target, end, source.parent)
            record["alpha_target"] = alpha
            if target_distance > tolerance:
                errors.append({"code": "target-miss", **record, "tolerance": tolerance})
            elif alpha == "transparent":
                warnings.append({"code": "target-transparent", **record})
            elif alpha == "outside":
                warnings.append({"code": "target-outside-raster", **record})
            if order.get(id(target), 0) > order.get(id(connector), 0) and local_name(target) != "text":
                warnings.append({"code": "arrowhead-may-be-covered", "id": cid, "target": target_id})
            check_source = args.check_all_sources or edge_spec.get("check_source", False)
            if check_source and source_id:
                source_el = elements.get(source_id)
                if source_el is None:
                    errors.append({"code": "missing-source", "id": cid, "source": source_id})
                else:
                    source_box = element_bbox(source_el, parents, args.font_regular, args.font_bold)
                    source_distance = distance(start, source_box)
                    record["source"] = source_id
                    record["source_distance"] = round(source_distance, 3)
                    if source_distance > tolerance:
                        errors.append({"code": "source-miss", **record, "tolerance": tolerance})
            checks.append(record)
        result = {
            "ok": not errors and (args.fail_on != "warning" or not warnings),
            "input": str(source), "input_sha256": sha256(source),
            "rendered": str(args.rendered.resolve()) if args.rendered else None,
            "text_policy": text_policy, "tolerance": args.tolerance,
            "tolerance_mode": args.tolerance_mode,
            "summary": {"ids": len(elements), "connectors": len(checks),
                        "source_checks": sum(1 for record in checks if "source_distance" in record),
                        "endpoint_checks": len(checks) + sum(1 for record in checks if "source_distance" in record),
                        "errors": len(errors), "warnings": len(warnings)},
            "checks": checks, "errors": errors, "warnings": warnings,
            "scope": "SVG declarations and geometry; scientific correctness requires separate evidence review",
        }
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"ok": result["ok"], "summary": result["summary"], "errors": errors[:12], "warnings": warnings[:12]}, ensure_ascii=False))
        if args.fail_on == "never":
            return 0
        if errors or (args.fail_on == "warning" and warnings):
            return 1
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "tool_error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
