"""Independent page facts of ONE PDF page for the table-cell evidence check (docs/G7_TABLE_CELL_CONTRACT_V1_CANDIDATE.md, section on the title scope).

Claude's own extraction, deliberately not Work's probe: what text lies in a given rectangle, which year-like strings it holds, how many separate drawn tables there are, and the box of the drawn table. It needs PyMuPDF
(imported inside the function, so the module can be imported without it) and only READS the bytes it is handed. Nothing is written, no network.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata


def _years(text: str) -> list[int]:
    flat = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))
    out = [int(y) for y in re.findall(r"(?<!\d)(20\d\d)年", flat)]
    out += [2018 + int(n) for n in re.findall(r"令和(\d{1,2})年", flat)]
    return out


def _cluster(rects: list[list[float]], gap: float) -> list[list[float]]:
    boxes = [list(r) for r in rects]
    merged = True
    while merged:
        merged = False
        out: list[list[float]] = []
        for b in boxes:
            for o in out:
                if b[0] <= o[2] + gap and o[0] <= b[2] + gap and b[1] <= o[3] + gap and o[1] <= b[3] + gap:
                    o[0], o[1], o[2], o[3] = min(o[0], b[0]), min(o[1], b[1]), max(o[2], b[2]), max(o[3], b[3])
                    merged = True
                    break
            else:
                out.append(b)
        boxes = out
    return boxes


def page_facts(pdf_bytes: bytes, page_no: int, scope: list[float], anchor_rect: list[float], *, min_table_area: float = 20000.0, gap: float = 8.0) -> dict:
    import fitz  # noqa: PLC0415  (optional dependency)

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        page = doc[page_no - 1]
        years_in_scope: list[dict] = []
        anchor_words: list[str] = []
        for b in page.get_text("dict")["blocks"]:
            if b["type"] != 0:
                continue
            for line in b["lines"]:
                r = line["bbox"]
                text = "".join(s["text"] for s in line["spans"])
                inside = r[0] >= scope[0] - 1 and r[1] >= scope[1] - 1 and r[2] <= scope[2] + 1 and r[3] <= scope[3] + 1
                if inside:
                    for y in _years(text):
                        years_in_scope.append({"year": y, "rect": [round(v, 1) for v in r]})
                if r[0] >= anchor_rect[0] - 2 and r[1] >= anchor_rect[1] - 2 and r[2] <= anchor_rect[2] + 2 and r[3] <= anchor_rect[3] + 2:
                    anchor_words.append(text)
        boxes = []
        for d in page.get_drawings():
            r = d["rect"]
            if r.width > 0 or r.height > 0:
                boxes.append([r.x0, r.y0, r.x1, r.y1])
        tables = [c for c in _cluster(boxes, gap) if (c[2] - c[0]) * (c[3] - c[1]) >= min_table_area and c[0] >= scope[0] - 1 and c[2] <= scope[2] + 1 and c[1] >= scope[1] - 1 and c[3] <= scope[3] + 1]
        return {"source_sha256": hashlib.sha256(pdf_bytes).hexdigest(), "years_in_scope": years_in_scope, "anchor_text_found": "".join(anchor_words), "table_clusters_in_scope": len(tables),
                "drawn_bbox": [round(min(t[0] for t in tables), 1), round(min(t[1] for t in tables), 1), round(max(t[2] for t in tables), 1), round(max(t[3] for t in tables), 1)] if tables else None}


def ink_extent(pdf_bytes: bytes, page_no: int, clip: list[float], *, threshold: int = 140, scale: int = 6) -> list[float] | None:
    """The bounding box, in points, of the DARK pixels inside `clip` (the drawn glyphs, not the font box). The caller passes a clip that excludes the ruling lines themselves (the interior of the ruled cell,
    inset by about 1.5 points), otherwise the rule would be measured. Pure Python (no numpy). Returns None when nothing dark is inside the clip."""
    import fitz  # noqa: PLC0415

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        pix = doc[page_no - 1].get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csGRAY, clip=fitz.Rect(*clip))
        w, h, n, data = pix.width, pix.height, pix.n, pix.samples
        x_min = y_min = None
        x_max = y_max = -1
        for y in range(h):
            row = data[y * w * n:(y + 1) * w * n:n]
            dark = [x for x, v in enumerate(row) if v < threshold]
            if dark:
                y_min = y if y_min is None else y_min
                y_max = y
                x_min = dark[0] if x_min is None else min(x_min, dark[0])
                x_max = max(x_max, dark[-1])
        if y_min is None:
            return None
        return [round(clip[0] + x_min / scale, 1), round(clip[1] + y_min / scale, 1), round(clip[0] + (x_max + 1) / scale, 1), round(clip[1] + (y_max + 1) / scale, 1)]
