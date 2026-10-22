"""Data/storage layer for Excel Vault; deliberately independent of Kivy for tests."""
from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd

def esc(value: str) -> str:
    """Escape Kivy markup delimiters without requiring Kivy in data-layer tests."""
    return str(value).replace("&", "&amp;").replace("[", "&bl;").replace("]", "&br;")


EXT = (".xlsx", ".xlsm", ".xls", ".ods", ".csv")
MAX_RESULTS = 3000
MAX_ROWS = 1500

# Desktop/Pydroid fallback; ExcelVaultApp switches this to App.user_data_dir at startup.
BASE = Path(__file__).resolve().parent / "storage"
FILES_DIR = BASE / "files"
PENDING_DIR = BASE / "pending"
INDEX = BASE / "index.json"
CACHE: dict[str, dict[str, "Sheet"]] = {}


class Sheet(NamedTuple):
    cols: list[str]
    df: pd.DataFrame
    first_row: int


def configure_storage(root: str | Path, legacy_path: str | Path | None = None) -> None:
    """Select the writable app-local directory and optionally migrate old desktop data."""
    global BASE, FILES_DIR, PENDING_DIR, INDEX
    new_base = Path(root).expanduser().resolve()
    old_base = Path(legacy_path).expanduser().resolve() if legacy_path else None

    BASE = new_base
    FILES_DIR = BASE / "files"
    PENDING_DIR = BASE / "pending"
    INDEX = BASE / "index.json"
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    PENDING_DIR.mkdir(parents=True, exist_ok=True)

    # Migrate the previous project-folder storage on first launch, when available.
    if old_base and old_base != BASE:
        old_index = old_base / "index.json"
        old_files = old_base / "files"
        if not INDEX.exists() and old_index.is_file():
            try:
                if old_files.is_dir():
                    shutil.copytree(old_files, FILES_DIR, dirs_exist_ok=True)
                shutil.copy2(old_index, INDEX)
            except OSError:
                # Migration is best-effort; normal app storage remains usable.
                pass

    CACHE.clear()


def load_index() -> list[dict]:
    try:
        data = json.loads(INDEX.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError, TypeError):
        return []


def save_index(items: list[dict]) -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    tmp = INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, INDEX)


def col_letter(i: int) -> str:
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _guess_delimiter(text: str) -> str:
    lines = [x for x in text.splitlines()[:30] if x.strip()]
    best, score = ",", 0
    for delimiter in ",;\t|":
        try:
            counts = [len(row) for row in csv.reader(lines, delimiter=delimiter)]
        except csv.Error:
            continue
        if counts and counts[0] > 1:
            current_score = counts.count(counts[0]) * 1000 + counts[0]
            if current_score > score:
                best, score = delimiter, current_score
    return best


def _read_csv(path: str | Path) -> pd.DataFrame:
    data = Path(path).read_bytes()
    text = None
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            pass
    if text is None:  # defensive; latin-1 can decode every byte
        text = data.decode("latin-1", errors="replace")

    # csv.field_size_limit is process-global; use a safe value supported by common builds.
    try:
        csv.field_size_limit(2**30)
    except (OverflowError, ValueError):
        csv.field_size_limit(2**31 - 1)
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=_guess_delimiter(text)))
    width = max((len(row) for row in rows), default=0)
    padded = [row + [""] * (width - len(row)) for row in rows]
    return pd.DataFrame(padded, dtype=str)


def _to_sheet(raw: pd.DataFrame) -> Sheet | None:
    """First non-empty row is the header; all following rows are searchable data."""
    if raw.empty:
        return None
    raw = raw.fillna("").astype(str)
    filled = raw.apply(lambda column: column.str.strip().ne("")).values.any(axis=1)
    if not filled.any():
        return None
    header_index = int(filled.argmax())
    cols = [value.strip() or "Kolom " + col_letter(i) for i, value in enumerate(raw.iloc[header_index])]
    return Sheet(cols, raw.iloc[header_index + 1 :].reset_index(drop=True), header_index + 2)


def read_sheets(path: str | Path) -> dict[str, Sheet]:
    """Read every worksheet as text. Raise ValueError if the file has no usable data."""
    file_path = Path(path)
    if file_path.suffix.lower() == ".csv":
        raw_sheets = {"CSV": _read_csv(file_path)}
    else:
        raw_sheets = pd.read_excel(file_path, sheet_name=None, header=None, dtype=str)
    output: dict[str, Sheet] = {}
    for name, raw in raw_sheets.items():
        sheet = _to_sheet(raw)
        if sheet is not None:
            output[str(name)] = sheet
    if not output:
        raise ValueError("File tidak berisi data")
    return output


def get_sheets(item: dict) -> dict[str, Sheet]:
    key = item["stored"]
    if key not in CACHE:
        CACHE[key] = read_sheets(FILES_DIR / key)
    return CACHE[key]


def store_uploaded_file(source: str | Path) -> tuple[dict, dict[str, Sheet]]:
    """Validate, copy into persistent app storage, and atomically add its index entry."""
    source_path = Path(source)
    if source_path.suffix.lower() not in EXT:
        raise ValueError("Format file tidak didukung")
    if not source_path.is_file():
        raise FileNotFoundError("File sumber tidak ditemukan")

    # Parse before copying so invalid/corrupt files are not added to the index.
    sheets = read_sheets(source_path)
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    stem_name = source_path.name
    stored = f"{time.time_ns()}_{stem_name}"
    while (FILES_DIR / stored).exists():
        stored = f"{time.time_ns()}_{stem_name}"
    destination = FILES_DIR / stored
    shutil.copy2(source_path, destination)

    item = {
        "name": stem_name,
        "stored": stored,
        "sheets": len(sheets),
        "rows": int(sum(len(sheet.df) for sheet in sheets.values())),
        "added": time.strftime("%Y-%m-%d %H:%M"),
    }
    try:
        index = load_index()
        index.append(item)
        save_index(index)
    except Exception:
        try:
            destination.unlink(missing_ok=True)
        finally:
            CACHE.pop(stored, None)
        raise
    CACHE[stored] = sheets
    return item, sheets


def clean(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ").replace("\t", " ")


def highlight(text: str, query: str) -> str:
    """Mark matching text using Kivy markup; source text is escaped first."""
    output, start = [], 0
    for match in re.finditer(re.escape(query), text, re.IGNORECASE):
        output.append(esc(text[start : match.start()]))
        output.append("[color=d9480f][b]%s[/b][/color]" % esc(match.group()))
        start = match.end()
    output.append(esc(text[start:]))
    return "".join(output)


def format_row(cols, values, hit=None, q=None, limit=80) -> str:
    parts = []
    for column_index, (name, value) in enumerate(zip(cols, values)):
        if value == "" and column_index != hit:
            continue
        value = clean(str(value))[:limit]
        if column_index == hit:
            header = "[b][color=3b49df]%s[/color][/b]" % esc(str(name)[:30])
        else:
            header = "[color=6b788c]%s[/color]" % esc(str(name)[:30])
        parts.append("%s %s" % (header, highlight(value, q) if q else esc(value)))
    return "    ".join(parts)


def search_tables(tables: list[dict], query: str, limit: int = MAX_RESULTS) -> dict:
    """Substring search over data cells (not headers), case-insensitive."""
    hits, cell_count, row_count = [], 0, 0
    counter = Counter()
    normalized_query = query.strip()
    if not normalized_query:
        return {"cells": 0, "rows": 0, "counter": counter, "hits": hits}

    for table_index, table in enumerate(tables):
        df = table["df"]
        if df.empty:
            continue
        mask = df.apply(
            lambda column: column.astype(str).str.contains(
                normalized_query, case=False, regex=False, na=False
            )
        ).to_numpy()
        row_indices, col_indices = mask.nonzero()
        cell_count += len(row_indices)
        row_count += int(np.unique(row_indices).size)
        for value in df.to_numpy()[mask]:
            counter.update([str(value).strip()])
        if limit > len(hits):
            for row_index, column_index in zip(row_indices.tolist(), col_indices.tolist()):
                if len(hits) >= limit:
                    break
                hits.append((table_index, row_index, column_index))
    return {"cells": cell_count, "rows": row_count, "counter": counter, "hits": hits}


def hit_card(table: dict, row_index: int, column_index: int, query: str) -> str:
    row = table["df"].iloc[row_index].tolist()
    excel_row = table["first_row"] + row_index
    return (
        "[b][color=3b49df]%s, %s[/color][/b]\n"
        "Sel [b]%s%d[/b] kolom %s:  %s\n"
        "Baris [b]%d[/b]:  %s"
    ) % (
        esc(table["file"]),
        esc(table["sheet"]),
        col_letter(column_index),
        excel_row,
        esc(table["cols"][column_index][:30]),
        highlight(clean(str(row[column_index]))[:300], query),
        excel_row,
        format_row(table["cols"], row, column_index, query),
    )
