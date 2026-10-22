# -*- coding: utf-8 -*-
"""Excel Vault — local Excel/spreadsheet search app built with Kivy."""
from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import ListProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.utils import escape_markup as esc
from kivy.utils import platform

import vault_core as core

INK = (0.106, 0.141, 0.188, 1)
ACCENT = (0.231, 0.286, 0.875, 1)
DANGER = (0.78, 0.22, 0.27, 1)
SURFACE = (1, 1, 1, 1)
ANDROID_PICKER_REQUEST = 7412


def go(screen: str) -> None:
    App.get_running_app().root.current = screen


def popup(title, msg, buttons, height=dp(230)):
    """buttons = [(label, callback|None, primary?)]"""
    box = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(14))
    label = Label(text=msg, markup=True, color=INK, halign="center", valign="middle")
    label.bind(width=lambda widget, width: setattr(widget, "text_size", (width, None)))
    box.add_widget(label)
    row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
    pop = Popup(
        title=title,
        content=box,
        auto_dismiss=False,
        size_hint=(None, None),
        size=(min(dp(460), Window.width * 0.92), height),
        background="",
        background_color=SURFACE,
        title_color=INK,
        separator_color=ACCENT,
    )
    for button_label, callback, primary in buttons:
        button = Button(
            text=button_label,
            bold=True,
            background_normal="",
            background_down="",
            background_color=ACCENT if primary else (0.9, 0.92, 0.95, 1),
            color=SURFACE if primary else INK,
        )

        def click(_instance, callback=callback):
            pop.dismiss()
            if callback:
                callback()

        button.bind(on_release=click)
        row.add_widget(button)
    box.add_widget(row)
    pop.open()
    return pop


class UploadScreen(Screen):
    queue = ListProperty([])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._android_activity_api = None
        self._android_bound = False
        self._android_import_busy = False

    def open_chooser(self):
        if platform == "android":
            self.open_android_chooser()
        else:
            self.open_desktop_chooser()

    def open_desktop_chooser(self):
        chooser = FileChooserListView(
            path=str(Path.home()),
            multiselect=True,
            filters=[lambda folder, name: name.lower().endswith(core.EXT)],
        )
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        box.add_widget(chooser)
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        cancel = Button(
            text="Batal", background_normal="", color=INK,
            background_color=(0.9, 0.92, 0.95, 1),
        )
        add = Button(
            text="Tambah file terpilih", bold=True, background_normal="",
            background_color=ACCENT, color=SURFACE,
        )
        row.add_widget(cancel)
        row.add_widget(add)
        box.add_widget(row)
        pop = Popup(
            title="Pilih file Excel atau spreadsheet",
            content=box,
            size_hint=(0.95, 0.9),
            background="",
            background_color=SURFACE,
            title_color=INK,
            separator_color=ACCENT,
        )
        cancel.bind(on_release=pop.dismiss)

        def add_selected(*_):
            self.add_files(chooser.selection)
            pop.dismiss()

        add.bind(on_release=add_selected)
        pop.open()

    def open_android_chooser(self):
        """Launch Android's Storage Access Framework; no broad storage permission needed."""
        if self._android_import_busy:
            popup("Sedang memproses", "Pemilihan atau penyalinan file sebelumnya masih berjalan.",
                  [("OK", None, True)], height=dp(180))
            return
        try:
            from android import activity
            from jnius import autoclass, cast

            Intent = autoclass("android.content.Intent")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            native_activity = cast("android.app.Activity", PythonActivity.mActivity)

            if not self._android_bound:
                activity.bind(on_activity_result=self._on_android_activity_result)
                self._android_bound = True
            self._android_activity_api = activity
            self._android_native_activity = native_activity

            intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            intent.setType("*/*")
            intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, True)
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            native_activity.startActivityForResult(intent, ANDROID_PICKER_REQUEST)
        except Exception as exc:
            popup(
                "Penyimpanan tidak dapat dibuka",
                "Pemilih dokumen Android gagal dibuka.\n%s" % esc(str(exc)[:220]),
                [("OK", None, True)], height=dp(230),
            )

    def _on_android_activity_result(self, *args):
        # Kivy/android versions differ on whether the dispatcher is included in callback args.
        if len(args) < 3:
            return
        request_code, result_code, result_intent = args[-3:]
        try:
            request_code = int(request_code)
            result_code = int(result_code)
        except (TypeError, ValueError):
            return
        if request_code != ANDROID_PICKER_REQUEST:
            return
        if result_code != -1 or result_intent is None:  # user cancelled
            return

        uris = []
        try:
            clip_data = result_intent.getClipData()
            if clip_data is not None:
                for index in range(int(clip_data.getItemCount())):
                    uri = clip_data.getItemAt(index).getUri()
                    if uri is not None:
                        uris.append(uri)
            else:
                uri = result_intent.getData()
                if uri is not None:
                    uris.append(uri)
        except Exception as exc:
            popup("File tidak terbaca", "Tidak bisa membaca pilihan file.\n%s" % esc(str(exc)[:180]),
                  [("OK", None, True)], height=dp(210))
            return

        if not uris:
            return
        self._android_import_busy = True
        try:
            resolver = self._android_native_activity.getContentResolver()
            reserved = {Path(path).name for path in self.queue}
            worker = threading.Thread(
                target=self._copy_android_uris_worker,
                args=(uris, resolver, reserved),
                daemon=True,
            )
            worker.start()
        except Exception as exc:
            self._android_import_busy = False
            popup("Gagal mengakses penyimpanan", esc(str(exc)[:220]), [("OK", None, True)], height=dp(200))

    def _display_name_from_uri(self, uri, resolver) -> str:
        from jnius import autoclass

        OpenableColumns = autoclass("android.provider.OpenableColumns")
        cursor = resolver.query(uri, None, None, None, None)
        if cursor is not None:
            try:
                if cursor.moveToFirst():
                    column_index = int(cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME))
                    if column_index >= 0:
                        name = cursor.getString(column_index)
                        if name:
                            return str(name)
            finally:
                cursor.close()
        last_segment = uri.getLastPathSegment()
        return str(last_segment or "spreadsheet.xlsx")

    @staticmethod
    def _unique_pending_name(name: str, reserved: set[str]) -> str:
        safe_name = Path(str(name).replace("\\", "/")).name.strip()
        if not safe_name or safe_name in (".", ".."):
            safe_name = "spreadsheet.xlsx"
        suffix = Path(safe_name).suffix.lower()
        if suffix not in core.EXT:
            raise ValueError("Format tidak didukung: %s" % safe_name)
        stem = Path(safe_name).stem or "spreadsheet"
        candidate = safe_name
        number = 2
        while candidate in reserved or (core.PENDING_DIR / candidate).exists():
            candidate = "%s (%d)%s" % (stem, number, suffix)
            number += 1
        reserved.add(candidate)
        return candidate

    def _copy_one_android_uri(self, uri, resolver, reserved: set[str]) -> str:
        """Stream a SAF URI into a normal app-local temporary file using its file descriptor."""
        name = self._display_name_from_uri(uri, resolver)
        pending_name = self._unique_pending_name(name, reserved)
        core.PENDING_DIR.mkdir(parents=True, exist_ok=True)
        destination = core.PENDING_DIR / pending_name
        parcel_descriptor = None
        detached_fd = None
        try:
            parcel_descriptor = resolver.openFileDescriptor(uri, "r")
            if parcel_descriptor is None:
                raise OSError("Android tidak memberikan akses baca ke file ini")
            detached_fd = int(parcel_descriptor.detachFd())
            parcel_descriptor.close()
            parcel_descriptor = None
            with os.fdopen(detached_fd, "rb") as source, destination.open("wb") as target:
                detached_fd = None  # os.fdopen owns and closes the descriptor now.
                shutil.copyfileobj(source, target, length=1024 * 1024)
            if destination.stat().st_size <= 0:
                raise ValueError("File kosong atau tidak dapat dibaca")
            return str(destination)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            if parcel_descriptor is not None:
                try:
                    parcel_descriptor.close()
                except Exception:
                    pass
            if detached_fd is not None:
                try:
                    os.close(detached_fd)
                except OSError:
                    pass

    def _copy_android_uris_worker(self, uris, resolver, reserved):
        paths, errors = [], []
        for uri in uris:
            try:
                paths.append(self._copy_one_android_uri(uri, resolver, reserved))
            except Exception as exc:
                errors.append(str(exc)[:180])
        Clock.schedule_once(lambda _dt: self._finish_android_import(paths, errors), 0)

    def _finish_android_import(self, paths, errors):
        self._android_import_busy = False
        self.add_files(paths)
        if errors:
            msg = "%d file masuk antrean." % len(paths)
            msg += "\n\nTidak berhasil:\n" + "\n".join(esc(error) for error in errors[:5])
            popup("Hasil akses penyimpanan", msg, [("OK", None, True)],
                  height=dp(min(380, 200 + 28 * min(len(errors), 5))))

    def add_files(self, paths):
        for item in paths:
            path = os.fspath(item)
            if path.lower().endswith(core.EXT) and os.path.isfile(path) and path not in self.queue:
                self.queue.append(path)
        self.refresh()

    def remove(self, path):
        if path in self.queue:
            self.queue.remove(path)
        # The Android SAF copy is only staging data; discard it when removed from the queue.
        try:
            candidate = Path(path).resolve()
            if candidate.parent == core.PENDING_DIR.resolve():
                candidate.unlink(missing_ok=True)
        except OSError:
            pass
        self.refresh()

    def refresh(self):
        if "qbox" not in self.ids:
            return
        box = self.ids.qbox
        box.clear_widgets()
        for path in self.queue:
            row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
            try:
                file_size_kb = os.path.getsize(path) / 1024
            except OSError:
                file_size_kb = 0
            name = esc(os.path.basename(path))
            label = Label(
                text="%s   [color=6b788c](%s KB)[/color]" % (name, format(file_size_kb, ",.0f")),
                markup=True, color=INK, halign="left", valign="middle",
                shorten=True, shorten_from="center",
            )
            label.bind(size=lambda widget, size: setattr(widget, "text_size", size))
            button = Button(
                text="Hapus", size_hint_x=None, width=dp(80), bold=True,
                background_normal="", background_color=DANGER, color=SURFACE,
            )
            button.bind(on_release=lambda _button, path=path: self.remove(path))
            row.add_widget(label)
            row.add_widget(button)
            box.add_widget(row)
        count = len(self.queue)
        self.ids.hint.text = (
            "%d file siap disimpan. Tekan Simpan untuk melanjutkan." % count if count else
            "Belum ada file. Tekan Tambah File untuk memilih .xlsx, .xls, .xlsm, .ods atau .csv."
        )

    def ask_save(self):
        if not self.queue:
            popup("Belum ada file", "Tambahkan minimal satu file terlebih dahulu.",
                  [("OK", None, True)], height=dp(190))
            return
        popup(
            "Konfirmasi penyimpanan",
            "Simpan [b]%d[/b] file ke penyimpanan lokal aplikasi?" % len(self.queue),
            [("Batal", None, False), ("Ya, simpan", self.save, True)],
            height=dp(200),
        )

    def save(self):
        succeeded, errors = 0, []
        for path in list(self.queue):
            try:
                core.store_uploaded_file(path)
                self.queue.remove(path)
                succeeded += 1
                try:
                    source = Path(path).resolve()
                    if source.parent == core.PENDING_DIR.resolve():
                        source.unlink(missing_ok=True)
                except OSError:
                    pass
            except Exception as exc:
                errors.append("%s: %s" % (os.path.basename(path), str(exc)[:120]))
        self.refresh()
        message = "[b]%d[/b] file berhasil disimpan di penyimpanan lokal." % succeeded
        if errors:
            message += "\n\nTidak berhasil:\n" + "\n".join(esc(error) for error in errors[:8])
        popup(
            "Hasil penyimpanan", message,
            [("Upload lagi", None, False), ("Buka Dashboard", lambda: go("dashboard"), True)],
            height=dp(min(450, 230 + 28 * min(len(errors), 8))),
        )


class DashboardScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.tables, self.failed, self.nfiles, self._event = [], [], 0, None

    def reload(self):
        self.tables, self.failed, self.nfiles = [], [], 0
        for item in core.load_index():
            try:
                for sheet_name, sheet in core.get_sheets(item).items():
                    self.tables.append({
                        "file": item["name"], "sheet": sheet_name, "cols": sheet.cols,
                        "rows": sheet.rows, "first_row": sheet.first_row,
                    })
                self.nfiles += 1
            except Exception:
                self.failed.append(str(item.get("name", "?")))
        self.run_search()

    def on_query(self, _text):
        if self._event:
            self._event.cancel()
        self._event = Clock.schedule_once(lambda _dt: self.run_search(), 0.2)

    def clear(self):
        if self._event:
            self._event.cancel()
        self.ids.q.text = ""
        self.ids.q.focus = True
        self.run_search()

    def _note(self):
        if not self.failed:
            return ""
        return "\n[color=c73a45]%d file gagal dibaca: %s[/color]" % (
            len(self.failed), esc(", ".join(self.failed)[:120])
        )

    def run_search(self):
        query = self.ids.q.text.strip()
        if not self.tables:
            self.ids.summary.text = "Belum ada data. Buka menu Upload untuk menambahkan file." + self._note()
            self.ids.rv.data = []
        elif query:
            self.show_matches(query)
        else:
            self.show_all()

    def show_all(self):
        items, rows, cells = [], 0, 0
        for table in self.tables:
            data_rows = table["rows"]
            rows += len(data_rows)
            cells += len(data_rows) * len(table["cols"])
            for index, row in enumerate(data_rows):
                if len(items) >= core.MAX_ROWS:
                    break
                items.append({"text":
                    "[b][color=3b49df]%s, %s[/color][/b]\nBaris [b]%d[/b]:  %s" % (
                        esc(table["file"]), esc(table["sheet"]), table["first_row"] + index,
                        core.format_row(table["cols"], row),
                    )
                })
        note = ""
        if rows > core.MAX_ROWS:
            note = "\n[color=6b788c]Menampilkan %d baris pertama. Gunakan pencarian untuk menemukan data lain.[/color]" % core.MAX_ROWS
        self.ids.summary.text = (
            "[b]%d[/b] file, [b]%d[/b] sheet, [b]%s[/b] baris data, [b]%s[/b] sel%s%s" % (
                self.nfiles, len(self.tables), format(rows, ","), format(cells, ","), note, self._note()
            )
        )
        self.ids.rv.data = items
        self.ids.rv.scroll_y = 1

    def show_matches(self, query):
        result = core.search_tables(self.tables, query)
        if not result["cells"]:
            self.ids.summary.text = "Tidak ada sel yang mengandung [b]%s[/b]." % esc(query) + self._note()
            self.ids.rv.data = []
            return
        top = ",  ".join(
            "%s x%d" % (esc(core.clean(value)[:30]), count)
            for value, count in result["counter"].most_common(8)
        )
        note = (
            "\n[color=6b788c]Hanya %d hasil pertama yang ditampilkan.[/color]" % core.MAX_RESULTS
            if result["cells"] > core.MAX_RESULTS else ""
        )
        self.ids.summary.text = (
            "[b]%s[/b] sel cocok dengan [b]%s[/b] pada [b]%s[/b] baris, [b]%d[/b] nilai berbeda\n"
            "[color=6b788c]Terbanyak: %s[/color]%s%s" % (
                format(result["cells"], ","), esc(query), format(result["rows"], ","),
                len(result["counter"]), top, note, self._note(),
            )
        )
        self.ids.rv.data = [
            {"text": core.hit_card(self.tables[table_index], row_index, col_index, query)}
            for table_index, row_index, col_index in result["hits"]
        ]
        self.ids.rv.scroll_y = 1


KV = """
#:import dp kivy.metrics.dp
#:import sp kivy.metrics.sp
#:set INK (0.106, 0.141, 0.188, 1)
#:set MUTED (0.42, 0.47, 0.55, 1)
#:set ACCENT (0.231, 0.286, 0.875, 1)

<Btn@Button>:
    background_normal: ''
    background_down: ''
    background_color: ACCENT
    color: 1, 1, 1, 1
    bold: True

<Quiet@Button>:
    background_normal: ''
    background_down: ''
    background_color: 1, 1, 1, 1
    color: ACCENT
    bold: True

<Title@Label>:
    color: INK
    bold: True
    font_size: sp(22)
    halign: 'left'
    valign: 'middle'
    text_size: self.size

<Info@Label>:
    color: MUTED
    markup: True
    halign: 'left'
    valign: 'top'
    size_hint_y: None
    text_size: self.width, None
    height: self.texture_size[1] + dp(8)

<Card@Label>:
    color: INK
    markup: True
    halign: 'left'
    valign: 'middle'
    size_hint_y: None
    text_size: self.width - dp(28), None
    height: self.texture_size[1] + dp(22)
    canvas.before:
        Color:
            rgba: 1, 1, 1, 1
        Rectangle:
            pos: self.x, self.y + dp(2)
            size: self.width, self.height - dp(4)

<UploadScreen>:
    name: 'upload'
    BoxLayout:
        orientation: 'vertical'
        padding: dp(16)
        spacing: dp(12)
        BoxLayout:
            size_hint_y: None
            height: dp(48)
            spacing: dp(8)
            Title:
                text: 'Upload file'
            Quiet:
                text: 'Dashboard'
                size_hint_x: None
                width: dp(120)
                on_release: app.root.current = 'dashboard'
        Info:
            id: hint
            text: ''
            color: INK
        ScrollView:
            GridLayout:
                id: qbox
                cols: 1
                size_hint_y: None
                height: self.minimum_height
                spacing: dp(6)
        BoxLayout:
            size_hint_y: None
            height: dp(48)
            spacing: dp(8)
            Quiet:
                text: '+ Tambah File'
                on_release: root.open_chooser()
            Btn:
                text: 'Simpan'
                on_release: root.ask_save()

<DashboardScreen>:
    name: 'dashboard'
    on_pre_enter: root.reload()
    BoxLayout:
        orientation: 'vertical'
        padding: dp(16)
        spacing: dp(10)
        BoxLayout:
            size_hint_y: None
            height: dp(48)
            spacing: dp(8)
            Title:
                text: 'Dashboard'
            Quiet:
                text: 'Upload'
                size_hint_x: None
                width: dp(100)
                on_release: app.root.current = 'upload'
        BoxLayout:
            size_hint_y: None
            height: dp(46)
            spacing: dp(8)
            TextInput:
                id: q
                hint_text: 'Cari teks di dalam sel...'
                multiline: False
                write_tab: False
                font_size: sp(16)
                padding: dp(12), dp(12)
                background_normal: ''
                background_active: ''
                background_color: 1, 1, 1, 1
                foreground_color: INK
                hint_text_color: MUTED
                cursor_color: ACCENT
                on_text: root.on_query(self.text)
            Btn:
                text: 'Clear'
                size_hint_x: None
                width: dp(90)
                on_release: root.clear()
        Info:
            id: summary
            text: ''
            color: INK
        RecycleView:
            id: rv
            viewclass: 'Card'
            bar_width: dp(6)
            RecycleBoxLayout:
                default_size: None, None
                default_size_hint: 1, None
                size_hint_y: None
                height: self.minimum_height
                orientation: 'vertical'
                spacing: dp(2)
"""


class ExcelVaultApp(App):
    title = "Excel Vault"

    def build(self):
        Window.clearcolor = (0.933, 0.945, 0.965, 1)
        if platform in ("win", "linux", "macosx"):
            Window.size = (1000, 680)

        # On Android user_data_dir points to writable app-local storage; on desktop it is
        # likewise a persistent per-user application directory. Never write to APK assets.
        core.configure_storage(
            Path(self.user_data_dir) / "storage",
            legacy_path=Path(__file__).resolve().parent / "storage",
        )
        Builder.load_string(KV)
        screen_manager = ScreenManager()
        upload_screen = UploadScreen()
        screen_manager.add_widget(upload_screen)
        screen_manager.add_widget(DashboardScreen())
        if core.load_index():
            screen_manager.current = "dashboard"
        # Refresh ids after KV is loaded/attached.
        Clock.schedule_once(lambda _dt: upload_screen.refresh(), 0)
        return screen_manager


if __name__ == "__main__":
    ExcelVaultApp().run()
