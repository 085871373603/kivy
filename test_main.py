"""Automated data-layer tests. Run: pytest -v test_main.py"""
import json
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook

import vault_core as core


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path):
    core.configure_storage(tmp_path / "appdata")
    yield
    core.CACHE.clear()


def make_workbook(path: Path):
    workbook = Workbook()
    first = workbook.active
    first.title = "Produk"
    first.append([None, None])  # blank row before header is allowed
    first.append(["Kode", "Nama Produk"])
    first.append(["A001", "Kopi Arabika"])
    first.append(["A002", "Kopi Robusta"])
    second = workbook.create_sheet("Cabang")
    second.append(["Cabang", "Keterangan"])
    second.append(["Karawang", "Stok kopi tersedia"])
    workbook.save(path)


def test_csv_detects_semicolon_and_header_is_not_searched(tmp_path):
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("\ufeffKode;Nama;HeaderJanganCari\nA01;Beras;Catatan biasa\nA02;Gula;Barang masuk\n", encoding="utf-8")

    sheets = core.read_sheets(csv_file)
    sheet = sheets["CSV"]
    assert sheet.cols == ["Kode", "Nama", "HeaderJanganCari"]
    assert sheet.first_row == 2
    assert len(sheet.df) == 2

    table = {"file": "data.csv", "sheet": "CSV", "cols": sheet.cols,
             "df": sheet.df, "first_row": sheet.first_row}
    assert core.search_tables([table], "HeaderJanganCari")["cells"] == 0
    assert core.search_tables([table], "beras")["cells"] == 1


def test_xlsx_reads_multiple_sheets_and_returns_excel_row_numbers(tmp_path):
    workbook_file = tmp_path / "inventory.xlsx"
    make_workbook(workbook_file)

    sheets = core.read_sheets(workbook_file)
    assert set(sheets) == {"Produk", "Cabang"}
    assert sheets["Produk"].first_row == 3
    assert sheets["Produk"].cols == ["Kode", "Nama Produk"]
    assert sheets["Produk"].df.iloc[0, 1] == "Kopi Arabika"
    assert sheets["Cabang"].first_row == 2

    tables = [
        {"file": workbook_file.name, "sheet": name, "cols": sheet.cols,
         "df": sheet.df, "first_row": sheet.first_row}
        for name, sheet in sheets.items()
    ]
    result = core.search_tables(tables, "kopi")
    assert result["cells"] == 3
    assert result["rows"] == 3
    assert len(result["hits"]) == 3
    table_index, row_index, column_index = result["hits"][0]
    card = core.hit_card(tables[table_index], row_index, column_index, "kopi")
    assert "Sel [b]B3[/b]" in card
    assert "Kopi" in card
    assert "Kode" in card  # complete row, not only matching cell


def test_search_counts_all_hits_but_limits_displayed_results(tmp_path):
    path = tmp_path / "many.csv"
    path.write_text("Code,First,Second\n1,cat,cat\n2,cat,dog\n3,dog,cat\n", encoding="utf-8")
    sheet = core.read_sheets(path)["CSV"]
    table = {"file": "many.csv", "sheet": "CSV", "cols": sheet.cols,
             "df": sheet.df, "first_row": sheet.first_row}

    result = core.search_tables([table], "cat", limit=2)
    assert result["cells"] == 4
    assert result["rows"] == 3
    assert len(result["hits"]) == 2
    assert result["counter"]["cat"] == 4


def test_uploaded_file_is_copied_and_index_survives_reload(tmp_path):
    source = tmp_path / "source.xlsx"
    make_workbook(source)
    item, sheets = core.store_uploaded_file(source)

    stored_file = core.FILES_DIR / item["stored"]
    assert stored_file.is_file()
    assert item["name"] == "source.xlsx"
    assert item["sheets"] == 2
    assert len(core.load_index()) == 1
    assert sheets["Produk"].df.iloc[0, 1] == "Kopi Arabika"

    # Simulate app restart: clear in-memory cache and reload the persistent index/files.
    core.CACHE.clear()
    reloaded_index = core.load_index()
    assert reloaded_index[0]["stored"] == item["stored"]
    loaded_sheets = core.get_sheets(reloaded_index[0])
    assert loaded_sheets["Cabang"].df.iloc[0, 0] == "Karawang"

    raw_index = json.loads(core.INDEX.read_text(encoding="utf-8"))
    assert raw_index[0]["name"] == "source.xlsx"


def test_rejects_unsupported_extensions_and_empty_files(tmp_path):
    unsupported = tmp_path / "notes.txt"
    unsupported.write_text("some text", encoding="utf-8")
    with pytest.raises(ValueError, match="Format"):
        core.store_uploaded_file(unsupported)

    empty = tmp_path / "empty.csv"
    empty.write_text("\n, ,\n", encoding="utf-8")
    with pytest.raises(ValueError, match="tidak berisi data"):
        core.read_sheets(empty)


def test_migrates_previous_storage_directory_on_first_launch(tmp_path):
    old_source = tmp_path / "legacy-source.csv"
    old_source.write_text("Kode,Nama\n01,Data lama\n", encoding="utf-8")
    item, _ = core.store_uploaded_file(old_source)
    previous_base = core.BASE

    new_base = tmp_path / "new-app-user-data" / "storage"
    core.configure_storage(new_base, legacy_path=previous_base)

    migrated = core.load_index()
    assert len(migrated) == 1
    assert (core.FILES_DIR / item["stored"]).is_file()
    sheets = core.get_sheets(migrated[0])
    assert sheets["CSV"].df.iloc[0, 1] == "Data lama"
