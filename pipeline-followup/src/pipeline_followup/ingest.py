"""Read the pipeline workbook strictly read-only.

The file's bytes are read once into memory and parsed from there, so the original is never
opened for writing (this also works while the EA has it open in Excel).
"""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

from .config import column_candidates, FIELDS


@dataclass
class SheetData:
    path: Path
    sha256: str
    sheet_name: str
    sheet_names: list[str]
    header_row: int                      # 1-based Excel row
    headers: list[str]                   # cleaned header text per column ("" if blank)
    rows: list[tuple[int, list]]         # (excel_row_number, values aligned with headers)
    merged_ranges: int = 0
    skipped: dict = field(default_factory=dict)  # reason -> count


def norm_header(h) -> str:
    s = "" if h is None else str(h)
    s = s.replace("\n", " ").strip().lower()
    return re.sub(r"\s+", " ", s)


def _is_blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def read_workbook_bytes(path: Path) -> tuple[bytes, str]:
    data = path.read_bytes()  # read-only access; the file handle is closed immediately
    return data, hashlib.sha256(data).hexdigest()


def load_grid(data: bytes, sheet: str | None):
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)  # in-memory copy only
    names = wb.sheetnames
    if sheet:
        match = [n for n in names if n.strip().lower() == str(sheet).strip().lower()]
        if not match:
            raise ValueError(f"Sheet '{sheet}' not found. Sheets in the file: {', '.join(names)}")
        ws = wb[match[0]]
    else:
        ws = wb[names[0]]
    grid = [list(r) for r in ws.iter_rows(values_only=True)]
    width = max((len(r) for r in grid), default=0)
    for r in grid:
        r.extend([None] * (width - len(r)))
    # Merged cells: only the top-left cell holds the value - copy it into the whole range.
    merged = list(ws.merged_cells.ranges)
    for rng in merged:
        top = grid[rng.min_row - 1][rng.min_col - 1]
        for rr in range(rng.min_row, rng.max_row + 1):
            for cc in range(rng.min_col, rng.max_col + 1):
                if rr - 1 < len(grid) and cc - 1 < width:
                    grid[rr - 1][cc - 1] = top
    return ws.title, names, grid, len(merged)


def _known_header_names(cfg: dict) -> set[str]:
    from .mapping import FIELD_ALIASES

    names = set()
    for f in FIELDS:
        names.update(norm_header(c) for c in column_candidates(cfg, f))
        names.update(FIELD_ALIASES.get(f, []))
    return names


def detect_header_row(grid: list[list], cfg: dict, max_scan: int = 25) -> int:
    """Pick the row (0-based) within the first `max_scan` rows that looks most like a header."""
    known = _known_header_names(cfg)
    best, best_score = 0, -1.0
    for i, row in enumerate(grid[:max_scan]):
        cells = [norm_header(v) for v in row if not _is_blank(v)]
        if len(cells) < 2:
            continue
        strings = sum(1 for v in row if isinstance(v, str) and v.strip())
        hits = sum(1 for c in cells if c in known)
        score = hits * 3 + strings * 0.5 - (len(cells) - strings)
        if score > best_score:
            best, best_score = i, score
    return best


def read_sheet(path: Path, cfg: dict) -> SheetData:
    if not path.exists():
        raise FileNotFoundError(f"Spreadsheet not found: {path}")
    data, digest = read_workbook_bytes(path)
    title, names, grid, n_merged = load_grid(data, cfg["source"].get("sheet"))
    hr = cfg["source"].get("header_row", "auto")
    if isinstance(hr, int) and hr > 0:
        h_idx = hr - 1
    else:
        h_idx = detect_header_row(grid, cfg)
    raw_headers = grid[h_idx] if grid else []
    headers, seen = [], {}
    for h in raw_headers:
        t = "" if h is None else re.sub(r"\s+", " ", str(h)).strip()
        if t:
            seen[t.lower()] = seen.get(t.lower(), 0) + 1
            if seen[t.lower()] > 1:
                t = f"{t} ({seen[t.lower()]})"
        headers.append(t)

    rows, skipped = [], {"blank": 0, "section heading": 0}
    for i in range(h_idx + 1, len(grid)):
        vals = grid[i]
        non_blank = [v for v, h in zip(vals, headers) if not _is_blank(v)]
        if not non_blank:
            skipped["blank"] += 1
            continue
        if all(isinstance(v, str) for v in non_blank) and len({str(v).strip() for v in non_blank}) == 1 \
                and (len(non_blank) == 1 or len(non_blank) >= 3):
            # A lone text cell (or one merged across the row), e.g. "NORDICS": a section heading
            skipped["section heading"] += 1
            continue
        rows.append((i + 1, vals))
    return SheetData(path=path, sha256=digest, sheet_name=title, sheet_names=names,
                     header_row=h_idx + 1, headers=headers, rows=rows,
                     merged_ranges=n_merged, skipped=skipped)


def resolve_columns(sheet: SheetData, cfg: dict) -> tuple[dict[str, int], dict[str, list[str]]]:
    """Map tool fields -> column index using the config. Returns (mapping, unresolved)."""
    index = {norm_header(h): i for i, h in enumerate(sheet.headers) if h}
    mapping, unresolved = {}, {}
    for f in FIELDS:
        cands = column_candidates(cfg, f)
        hit = next((index[norm_header(c)] for c in cands if norm_header(c) in index), None)
        if hit is not None:
            mapping[f] = hit
        elif cands:
            unresolved[f] = cands
    return mapping, unresolved
