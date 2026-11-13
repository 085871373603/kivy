"""
Pengujian TIMER MAXDIS  ->  pytest -v test_main.py

1. Perhitungan, format, alur sesi, penyimpanan, dan reset saat start DIBANDINGKAN dengan hasil
   MENJALANKAN kode JavaScript asli di Node.js (golden.json, dibuat oleh tools/gen_golden.js).
2. Alur aplikasi (Controller) diuji dengan jam dan tampilan palsu: simulasi sesi lengkap per detik.
3. Kivy diganti stub ringan; tampilan KV diperiksa statis, render visual diuji manual di HP.
"""
import ast
import configparser
import contextlib
import json
import os
import re
import sys
import time
import types
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ["TZ"] = "Asia/Jakarta"          # golden.json dibuat pada zona waktu ini (tanpa DST)
time.tzset()
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


# ------------------------------------------------------------------ stub Kivy
def _install_kivy_stub():
    def mod(name, **kw):
        m = types.ModuleType(name)
        m.__dict__.update(kw)
        sys.modules[name] = m

    class W:
        def __init__(self, **kw):
            self.children, self._binds = [], {}
            self.__dict__.update(kw)
        def bind(self, **kw):
            for k, v in kw.items():
                self._binds.setdefault(k, []).append(v)
        def add_widget(self, w): self.children.append(w)
        def clear_widgets(self): self.children = []
        def on_touch_down(self, t): return False
        def on_touch_up(self, t): return False

    class Animation:
        repeat = False
        def __init__(self, **kw): pass
        def __add__(self, o): return self
        def start(self, w): pass
        @staticmethod
        def cancel_all(w, *a): pass

    class App:
        running = None
        @classmethod
        def get_running_app(cls): return cls.running

    class Clock:
        events = []
        @staticmethod
        def schedule_once(fn, t=0):
            e = SimpleNamespace(fn=fn, t=t, cancel=lambda: None); Clock.events.append(e); return e
        schedule_interval = schedule_once

    for n in ("kivy", "kivy.uix", "kivy.core"):
        mod(n); sys.modules[n].__path__ = []
    mod("kivy.animation", Animation=Animation)
    mod("kivy.app", App=App)
    mod("kivy.clock", Clock=Clock)
    mod("kivy.core.window", Window=SimpleNamespace(width=420, height=780, size=(420, 780), clearcolor=None, bind=lambda **k: None))
    mod("kivy.lang", Builder=SimpleNamespace(load_string=lambda s: None))
    mod("kivy.metrics", dp=lambda x: x, sp=lambda x: x)
    prop = lambda default=None: default
    mod("kivy.properties", BooleanProperty=prop, NumericProperty=prop, StringProperty=prop)
    for n, c in (("boxlayout", "BoxLayout"), ("button", "Button"), ("floatlayout", "FloatLayout"), ("label", "Label"),
                 ("modalview", "ModalView"), ("popup", "Popup"), ("textinput", "TextInput")):
        mod("kivy.uix." + n, **{c: type(c, (W,), {})})
    mod("kivy.utils", platform="linux")


_install_kivy_stub()
import logic as L  # noqa: E402
import main  # noqa: E402

MAIN_SRC = Path(main.__file__).read_text(encoding="utf-8")
LOGIC_SRC = Path(L.__file__).read_text(encoding="utf-8")
GOLDEN_PATH = HERE / "golden.json"
T0 = int(time.mktime((2026, 3, 2, 10, 0, 0, 0, 0, -1)) * 1000)       # 02/03/2026 10:00:00 WIB = SHIFT 1


def golden():
    if not GOLDEN_PATH.exists():
        pytest.fail("golden.json tidak ditemukan: unggah berkas ini bersama kode (kunci jawaban dari JavaScript asli).")
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


GOLD = golden()


def parsed(storage):
    return {k: json.loads(v) for k, v in storage.items()}


# ===================================================== 1. pembanding terhadap JavaScript asli
class TestAgainstOriginalJavaScript:
    def test_format_duration(self):
        for x, want in GOLD["format_duration"]:
            assert L.format_duration(float("nan") if x == "NaN" else x) == want, x

    def test_shift_dan_waktu_selesai(self):
        for t, want in GOLD["shift"]:
            assert L.get_shift(t) == want, t
        for t, want in GOLD["datetime"]:
            assert L.format_datetime(t) == want, t

    def test_angka_id_ID_dan_toFixed(self):
        for x, want in GOLD["number_id"]:
            assert L.format_number_id(x) == want, x
        for x, want in GOLD["fixed1"]:
            assert L.js_to_fixed(x, 1) == want, x

    def test_durasi_timer(self):
        for q, want in GOLD["ceil_duration"]:
            assert L.timer_seconds(q) == want, q

    def test_tampilan_timer_progres_pesan(self):
        for qty, elapsed, want in GOLD["tick"]:
            total = L.timer_seconds(qty)
            assert L.tick_info(5000 + total * 1000, total, 5000 + elapsed) == want, (qty, elapsed)

    def test_evaluasi_waktu_dan_batas_10_persen(self):
        for target, actual, want in GOLD["evaluate"]:
            assert L.evaluate_timing(target, actual) == want, (target, actual)

    def test_posisi_tooltip_tutorial(self):
        for rect, iw, ih, tip, want in GOLD["coach"]:
            assert L.coach_pos(rect, iw, ih, tip) == want, (rect, iw, ih, tip)

    def test_sesi_lengkap_hasil_status_dan_penyimpanan(self):
        for i, s in enumerate(GOLD["sessions"]):
            st = L.MemStorage()
            sess = L.TimerSession(st)
            res = None
            logs = iter(s["log"])
            for step in s["steps"]:
                sess.now = lambda v=step["start"]: v
                sess.start_timer(step["qty"])
                log = next(logs, None)
                if log:
                    assert parsed(st.as_dict()) == parsed(log["afterStart"]["storage"]), i
                    assert sess.current_total_seconds == log["afterStart"]["total"] and sess.timer_end_ms == log["afterStart"]["end"]
                sess.now = lambda v=step["finish"]: v
                sess.finish_timer()
                if log:
                    assert parsed(st.as_dict()) == parsed(log["afterFinish"]["storage"]), i
                done, res = sess.finish_lorong()
                if log:
                    assert res == log["result"], i
            assert res == s["result"], i
            snap, want = sess.snapshot(), s["final"]
            for k in ("currentIndex", "qtyHistory", "completedLorong", "sessionStartTimestampMs", "sessionRecords"):
                assert snap[k] == want[k], (i, k)
            assert parsed(snap["storage"]) == parsed(want["storage"]), i

    def test_reset_saat_start_semua_kombinasi(self):
        assert len(GOLD["startup"]) >= 400
        for i, sc in enumerate(GOLD["startup"]):
            sess = L.TimerSession(L.MemStorage(sc["storage"]))
            sess.process_startup_reset(sc["nav"])
            snap, want = sess.snapshot(), sc["after"]
            for k in ("currentIndex", "qtyHistory", "completedLorong", "sessionStartTimestampMs", "sessionRecords"):
                assert snap[k] == want[k], (i, sc["nav"], sc["storage"], k)
            assert parsed(snap["storage"]) == parsed(want["storage"]), i


# ===================================================== 2. logika inti (dihitung tangan)
class TestLogic:
    @pytest.mark.parametrize("v,want", [(None, 0), (True, 1), ("5", 5), (" 7 ", 7), ("", 0), ("0x10", 16), ([], 0), ([3], 3), ("1e3", 1000), (-2.5, -2.5)])
    def test_js_number(self, v, want):
        assert L.js_number(v) == want

    @pytest.mark.parametrize("v", ["abc", "1,5", "nan", {}, [1, 2], L.UNDEF, "12px"])
    def test_js_number_nan(self, v):
        assert L.js_number(v) != L.js_number(v)

    def test_pembulatan_gaya_javascript(self):
        assert [L.js_round(x) for x in (0.5, 1.5, 2.5, -2.5, 59.49)] == [1, 2, 3, -2, 59]       # bukan pembulatan bankir
        assert [L.format_duration(x) for x in (0.4, 0.5, 2.5, 59.5, 3599.5, 3600, -9)] == ["00:00", "00:01", "00:03", "01:00", "01:00:00", "01:00:00", "00:00"]

    def test_durasi_contoh_nyata_termasuk_keunikan_floating_point_js(self):
        assert [L.timer_seconds(q) for q in (1, 7, 12, 13, 60, 24, 2.5, 0.5)] == [5, 35, 60, 65, 300, 120, 13, 3]
        # Keunikan kode asli: (100/12)*60 = 500.00000000000006 di JavaScript, sehingga ceil() = 501 (bukan 500).
        # Dipertahankan apa adanya ("jangan ubah apa pun"); dibuktikan sama dengan Node.js lewat golden.json.
        assert L.timer_seconds(100) == 501 and (100 / 12) * 60 > 500
        assert [q for q, want in GOLD["ceil_duration"] if q == 100 and want == 501]

    def test_tampilan_timer_per_menit_dan_pesan(self):
        total = 125                                                                       # > 99 menit juga aman
        i = L.tick_info(125000, total, 0)
        assert (i["display"], i["message"], i["progressPercent"]) == ("02:05", "Waktu berjalan.", 100.0)
        assert L.tick_info(125000, total, 64000)["message"] == "Waktu berjalan."          # 61 detik tersisa
        assert L.tick_info(125000, total, 65000)["message"] == "Tinggal sebentar lagi."  # tepat 60 detik tersisa
        assert L.tick_info(125000, total, 95000)["message"] == "30 detik terakhir."
        assert L.tick_info(125000, total, 115000)["message"] == "Hampir selesai!"
        end = L.tick_info(125000, total, 125000)
        assert end["finished"] and end["display"] == "00:00" and end["progressPercent"] == 0
        assert L.tick_info(6000000, 6000, 0)["display"] == "100:00"

    def test_penyimpanan_berkas_atomik(self, tmp_path):
        fs = L.FileStorage(tmp_path / "s")
        assert fs.get("a") is None
        fs.set("a", "1"); fs.set("a", 2)
        assert fs.get("a") == "2" and not list((tmp_path / "s").glob("*.tmp"))
        fs.remove("a"); fs.remove("tidak-ada")
        assert fs.get("a") is None
        fs.set("kunci/aneh:1", "x")
        assert L.FileStorage(tmp_path / "s").get("kunci/aneh:1") == "x"                   # tersimpan lintas buka-ulang

    def test_start_menyimpan_state_seperti_aslinya(self):
        st = L.MemStorage()
        s = L.TimerSession(st, lambda: T0)
        s.start_timer(12)
        assert json.loads(st.get(L.TIMER_KEY)) == {"running": True, "index": 0, "qty": 12, "total": 60, "end": T0 + 60000, "start": T0}
        assert s.session_start_ms == T0 and s.is_running and not any(s.completed)
        s.is_running = False
        s.session_start_ms = 0
        s.records.append({"index": 0})                                                    # lorong 1 sudah punya catatan: awal sesi tidak berubah
        s.start_timer(12)
        assert s.session_start_ms == 0

    def test_awal_sesi_hanya_dari_lorong_1(self):
        s = L.TimerSession(L.MemStorage(), lambda: T0)
        s.current_index = 2                                                               # catatan kosong tetapi bukan lorong 1 (data sesi janggal)
        s.start_timer(12)
        assert s.session_start_ms == 0                                                    # currentIndex === 0 && sessionRecords.length === 0

    def test_selesai_dua_kali_diabaikan(self):
        s = L.TimerSession(L.MemStorage(), lambda: T0)
        assert s.finish_timer() is False
        s.start_timer(12)
        assert s.finish_timer() is True and s.finish_timer() is False and len(s.records) == 1

    def test_hasil_belum_lengkap_adalah_none(self):
        s = L.TimerSession(L.MemStorage(), lambda: T0)
        s.start_timer(12); s.finish_timer()
        assert s.finish_lorong() == (False, None) and s.result() is None and s.current_index == 1

    def test_url_menu(self):
        assert L.menu_url("https://x.com/timer/") == "https://x.com/timer/menu.html"
        assert L.menu_url("https://x.com/timer/index.html") == "https://x.com/timer/menu.html"
        assert L.menu_url("https://x.com/timer") == "https://x.com/menu.html"             # sama seperti browser: 'timer' dianggap berkas
        assert L.menu_url("http://192.168.1.5:8080/a/b.html?x=1#h") == "http://192.168.1.5:8080/a/menu.html"
        assert L.normalize_page_url(" x.com/timer/ ") == "https://x.com/timer/"
        for bad in ("", "   ", "ftp://x.com", "https://", "a b"):
            with pytest.raises(ValueError):
                L.normalize_page_url(bad)

    def test_posisi_tooltip_contoh(self):
        r = {"left": 16, "top": 8, "width": 72, "height": 40, "bottom": 48}
        assert L.coach_pos(r, 420, 780, 120) == {"left": 10, "top": 63}                  # di bawah target, kiri dijepit 10
        low = {"left": 300, "top": 700, "width": 60, "height": 40, "bottom": 740}
        assert L.coach_pos(low, 420, 780, 120) == {"left": 150, "top": 565}              # tidak muat di bawah -> di atas target


# ===================================================== 3. alarm: gelombang kotak 900 Hz, 500 ms
class TestBeep:
    def test_wav_sesuai_beep_asli(self, tmp_path):
        p = L.make_beep_wav(tmp_path / "beep.wav")
        with wave.open(p) as w:
            assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 22050)
            n = w.getnframes()
            frames = w.readframes(n)
        import struct
        s = struct.unpack("<%dh" % n, frames)
        assert abs(n / 22050 - 0.5) < 0.002                                               # 500 ms
        steady = s[int(0.05 * 22050):int(0.4 * 22050)]
        crossings = sum(1 for a, b in zip(steady, steady[1:]) if (a >= 0) != (b >= 0))
        freq = crossings / 2 / (len(steady) / 22050)
        assert 880 <= freq <= 920                                                          # 900 Hz
        assert max(abs(x) for x in s[:int(0.002 * 22050)]) < max(abs(x) for x in s[int(0.015 * 22050):int(0.03 * 22050)])  # naik dalam 20 ms
        assert max(abs(x) for x in s[-30:]) < 0.05 * 32767                                 # menurun ke 0 di akhir
        assert 0.5 * 32767 < max(abs(x) for x in s) <= 0.9 * 32767                         # gain 0,9


# ===================================================== 4. alur aplikasi (Controller) dengan jam & tampilan palsu
class Ev:
    def __init__(self, kind, period, due, fn, seq):
        self.kind, self.period, self.due, self.fn, self.seq, self.cancelled = kind, period, due, fn, seq, False


class FakeSvc:
    """Jam, penjadwal, alarm, layar, dan browser palsu: waktu hanya maju bila diminta."""
    def __init__(self, t=T0):
        self.t, self.events, self.beeps, self.screen, self.opened, self.open_error, self._seq = t, [], [], [], [], None, 0

    def now(self): return int(self.t)

    def _add(self, kind, seconds, fn):
        self._seq += 1
        ev = Ev(kind, seconds * 1000, self.t + seconds * 1000, fn, self._seq)
        self.events.append(ev)
        return ev

    def every(self, seconds, fn): return self._add("every", seconds, fn)
    def later(self, seconds, fn): return self._add("later", seconds, fn)

    def cancel(self, ev):
        if ev is not None:
            ev.cancelled = True

    def beep(self): self.beeps.append(int(self.t))
    def keep_screen_on(self, on): self.screen.append(on)

    def open_url(self, url):
        if self.open_error:
            raise self.open_error
        self.opened.append(url)

    def run_until(self, target):
        while True:
            due = [e for e in self.events if not e.cancelled and e.due <= target]
            if not due:
                break
            e = min(due, key=lambda x: (x.due, x.seq))
            self.t = max(self.t, e.due)
            if e.kind == "every":
                e.due += e.period
            else:
                e.cancelled = True
            e.fn()
        self.t = target

    def run_for(self, ms): self.run_until(self.t + ms)


RECT = {"left": 20, "top": 100, "width": 64, "height": 40, "bottom": 140, "_x": 20, "_y": 600, "_w": 64, "_h": 40}


class FakeUI:
    def __init__(self):
        self.calls, self.targets, self.server_cb, self.server_prefill = [], {"btn_menu": dict(RECT), "input_0": dict(RECT)}, None, None

    def _r(self, name, *a): self.calls.append((name,) + a)
    def names(self): return [c[0] for c in self.calls]
    def of(self, name): return [c for c in self.calls if c[0] == name]
    def last(self, name): return self.of(name)[-1]

    def render_list(self, index, qh, done): self._r("render_list", index, list(qh), list(done))
    def set_stepper(self, step): self._r("set_stepper", step)
    def show_splash(self): self._r("show_splash")
    def fade_splash(self): self._r("fade_splash")
    def hide_splash(self): self._r("hide_splash")
    def focus_input(self, i): self._r("focus_input", i)
    def alert(self, text): self._r("alert", text)
    def show_timer(self, title, qty): self._r("show_timer", title, qty)
    def update_timer(self, display, progress, message): self._r("update_timer", display, progress, message)
    def show_timer_finished(self): self._r("show_timer_finished")
    def hide_timer(self): self._r("hide_timer")
    def show_result(self, r): self._r("show_result", r)
    def hide_result(self): self._r("hide_result")
    def coach_target_rect(self, name): return self.targets.get(name)
    def show_coach(self, rect, text, last): self._r("show_coach", text, last)
    def hide_coach(self): self._r("hide_coach")

    def ask_server_url(self, current, on_ok):
        self.server_prefill, self.server_cb = current, on_ok
        self._r("ask_server_url", current)


@pytest.fixture
def app(tmp_path):
    ui, svc, st = FakeUI(), FakeSvc(), L.FileStorage(tmp_path / "store")
    ctl = main.Controller(ui, st, svc)
    return SimpleNamespace(ui=ui, svc=svc, st=st, ctl=ctl, tmp=tmp_path)


def finish_coach(a):
    """Lewati splash + tutorial agar uji alur fokus pada timer."""
    a.ctl.init_app()
    a.svc.run_for(1200)
    a.ctl.next_coach(); a.ctl.next_coach()
    a.ui.calls.clear()


def play(a, qtys, press=4, enter=6):
    """Kerjakan lorong demi lorong dengan jeda (detik) antara selesai -> ketuk Lanjut -> Enter."""
    for i, q in enumerate(qtys):
        assert a.ctl.on_enter(i, str(q)), i
        a.svc.run_for(L.timer_seconds(q) * 1000)
        a.svc.run_for(press * 1000)
        a.ctl.next_lorong()
        if i < len(qtys) - 1:
            a.svc.run_for(enter * 1000)


class TestControllerStart:
    def test_init_membersihkan_sesi_lama_dan_splash_bertahap(self, app):
        app.st.set(L.SESSION_KEY, json.dumps({"index": 2, "qtyHistory": [5, 6, None, None, None, None]}))
        app.ctl.init_app()
        assert app.ui.names() == ["render_list", "set_stepper", "show_splash"] and app.ui.last("render_list")[1:] == (0, [None] * 6, [False] * 6)
        assert app.st.get(L.SESSION_KEY) is None                                          # dibuka biasa = sesi bersih (seperti 'navigate')
        app.svc.run_until(T0 + 699)
        assert "fade_splash" not in app.ui.names()
        app.svc.run_until(T0 + 700)
        assert "fade_splash" in app.ui.names() and "hide_splash" not in app.ui.names()
        app.svc.run_until(T0 + 1100)
        assert app.ui.names()[-2:] == ["hide_splash", "show_coach"]                       # splash 700 ms + pudar 400 ms, lalu tutorial

    def test_dibuka_ulang_saat_timer_berjalan_reset_lorong_aktif_saja(self, app):
        finish_coach(app)
        play(app, [12, 12])
        app.ctl.on_enter(2, "30")                                                         # lorong 3 sedang berjalan
        ui2, svc2 = FakeUI(), FakeSvc(app.svc.t + 5000)
        ctl2 = main.Controller(ui2, app.st, svc2)                                         # proses ditutup paksa lalu dibuka lagi
        ctl2.init_app()
        r = ui2.last("render_list")
        assert r[1] == 2 and r[2] == [12, 12, None, None, None, None] and r[3] == [True, True, False, False, False, False]
        assert app.st.get(L.TIMER_KEY) is None and not ctl2.session.is_running

    def test_dibuka_ulang_tanpa_timer_berjalan_sesi_dibersihkan(self, app):
        finish_coach(app)
        play(app, [12, 12])
        ctl2 = main.Controller(FakeUI(), app.st, FakeSvc(app.svc.t + 5000))
        ctl2.init_app()
        assert ctl2.session.qty_history == [None] * 6 and ctl2.session.current_index == 0

    def test_dibuka_ulang_saat_lorong_1_berjalan_semua_bersih(self, app):
        finish_coach(app)
        app.ctl.on_enter(0, "50")
        ctl2 = main.Controller(FakeUI(), app.st, FakeSvc(app.svc.t + 5000))
        ctl2.init_app()
        assert ctl2.session.session_start_ms == 0 and ctl2.session.records == [] and ctl2.session.qty_history == [None] * 6


class TestControllerInput:
    @pytest.mark.parametrize("text", ["", "   ", "0", "0,0", "-3", "abc", "1e", "NaN", "Infinity", "-0"])
    def test_qty_tidak_valid(self, app, text):
        finish_coach(app)
        assert app.ctl.on_enter(0, text) is False
        assert app.ui.calls == [("alert", "Masukkan Qty lebih dari 0.")]
        assert not app.ctl.session.is_running and app.st.get(L.TIMER_KEY) is None and app.svc.screen == []

    @pytest.mark.parametrize("text,qty,secs,label", [("12", 12, 60, "QTY 12"), (" 7 ", 7, 35, "QTY 7"), ("2,5", 2.5, 13, "QTY 2.5"), ("2.5", 2.5, 13, "QTY 2.5"),
                                                     ("1e2", 100, 501, "QTY 100"), ("0.5", 0.5, 3, "QTY 0.5")])
    def test_qty_valid_memulai_timer(self, app, text, qty, secs, label):
        finish_coach(app)
        assert app.ctl.on_enter(0, text) is True
        s = app.ctl.session
        assert s.is_running and s.current_qty == qty and s.current_total_seconds == secs and s.timer_end_ms == T0 + 1200 + secs * 1000
        assert app.ui.of("show_timer") == [("show_timer", "LORONG 1", label)]
        assert app.ui.last("update_timer")[1] == ("01:00" if secs == 60 else "%02d:%02d" % divmod(secs, 60))
        assert app.svc.screen == [True]                                                   # layar tetap menyala (wake lock)
        assert json.loads(app.st.get(L.TIMER_KEY))["running"] is True

    def test_input_lorong_lain_dan_enter_ganda_diabaikan(self, app):
        finish_coach(app)
        assert app.ctl.on_enter(3, "12") is False and app.ui.calls == []
        assert app.ctl.on_enter(0, "12") is True
        n = len(app.ui.calls)
        assert app.ctl.on_enter(0, "99") is False and len(app.ui.calls) == n and app.ctl.session.current_qty == 12
        assert app.ctl.on_enter(0, "abc") is False and app.ui.last("alert")                # validasi tetap dicek lebih dulu (seperti JS)


class TestRender:
    def test_stepper_proses_saat_timer_berjalan(self, app):
        finish_coach(app)
        app.ctl.render()
        assert app.ui.last("set_stepper") == ("set_stepper", 1)
        app.ctl.session.is_running = True
        app.ctl.render()
        assert app.ui.last("set_stepper") == ("set_stepper", 2)                           # setStepper(isTimerRunning ? 2 : 1)


class TestControllerTimer:
    def test_hitung_mundur_pesan_dan_selesai_tepat_waktu(self, app):
        finish_coach(app)
        app.ctl.on_enter(0, "24")                                                         # 120 detik
        start = app.ctl.session.timer_start_ms
        got = {}
        for sec in (0, 59, 60, 89, 90, 109, 110, 119):
            app.svc.run_until(start + sec * 1000)
            got[sec] = app.ui.last("update_timer")[1:]
        assert got[0] == ("02:00", 100.0, "Waktu berjalan.") and got[59] == ("01:01", pytest.approx(50.8333333), "Waktu berjalan.")
        assert got[60] == ("01:00", pytest.approx(50.0), "Tinggal sebentar lagi.") and got[89][0::2] == ("00:31", "Tinggal sebentar lagi.")
        assert got[90][0::2] == ("00:30", "30 detik terakhir.") and got[109][0::2] == ("00:11", "30 detik terakhir.")
        assert got[110][0::2] == ("00:10", "Hampir selesai!") and got[119][0::2] == ("00:01", "Hampir selesai!")
        assert "show_timer_finished" not in app.ui.names()
        app.svc.run_until(start + 120000)
        s = app.ctl.session
        assert not s.is_running and s.completed[0] and s.qty_history[0] == 24
        assert s.records == [{"index": 0, "code": "L01", "qty": 24, "start": start, "finish": start + 120000}]
        assert app.ui.names()[-3:] == ["update_timer", "show_timer_finished", "set_stepper"] and app.ui.last("set_stepper") == ("set_stepper", 3)
        assert app.ui.last("update_timer")[1] == "00:00" and app.svc.screen == [True, False] and app.st.get(L.TIMER_KEY) is None

    def test_alarm_langsung_lalu_tiap_detik_sampai_lanjut(self, app):
        finish_coach(app)
        app.ctl.on_enter(0, "12")
        app.svc.run_for(60000)
        finish = app.svc.t
        assert app.svc.beeps == [finish]
        app.svc.run_for(3000)
        assert app.svc.beeps == [finish, finish + 1000, finish + 2000, finish + 3000]
        app.ctl.next_lorong()
        app.svc.run_for(5000)
        assert len(app.svc.beeps) == 4                                                    # alarm berhenti saat Lanjut ditekan

    def test_lanjut_menyiapkan_lorong_berikutnya(self, app):
        finish_coach(app)
        app.ctl.on_enter(0, "12"); app.svc.run_for(60000)
        app.ui.calls.clear()
        app.ctl.next_lorong()
        assert app.ui.names() == ["hide_timer", "render_list", "set_stepper"]
        assert app.ui.last("render_list")[1:] == (1, [12, None, None, None, None, None], [True, False, False, False, False, False])
        assert app.ui.last("set_stepper") == ("set_stepper", 1)
        app.svc.run_for(149); assert "focus_input" not in app.ui.names()
        app.svc.run_for(1); assert app.ui.last("focus_input") == ("focus_input", 1)       # fokus ke input berikutnya setelah 150 ms
        assert app.ctl.session.current_index == 1 and not app.ctl.timer_visible

    def test_kembali_dari_latar_belakang_langsung_menyusul(self, app):
        finish_coach(app)
        app.ctl.on_enter(0, "12")
        app.svc.t += 45000                                                                # aplikasi dibekukan Android 45 dtk (jam jalan, tick tidak)
        app.ctl.on_resume()
        assert app.ui.last("update_timer")[1] == "00:15" and app.svc.screen[-1] is True
        app.svc.t += 30000                                                                # tertidur melewati batas waktu
        app.ctl.on_resume()
        assert not app.ctl.session.is_running and app.ui.last("show_timer_finished") and app.svc.beeps

    def test_resume_tanpa_timer_tidak_berbuat_apa_apa(self, app):
        finish_coach(app)
        app.ctl.on_resume()
        assert app.ui.calls == [] and app.svc.screen == []


class TestFullSession:
    def hasil(self, a):
        return a.ui.last("show_result")[1]

    def test_enam_lorong_gap_10_detik_dihitung_tangan(self, app):
        finish_coach(app)
        play(app, [12] * 6, press=4, enter=6)
        r = self.hasil(app)
        # lorong 60 dtk x6 = 06:00 kerja; jeda 10 dtk x5 = 00:50; aktual 06:50; total qty 72 -> standar 06:00; (410-360)/360 = +13,9%
        assert r == {"totalQty": "72", "shift": "SHIFT 1", "target": "06:00", "work": "06:00", "gap": "00:50", "actual": "06:50",
                     "percent": "+13.9%", "finishedAt": "02/03/2026, 10.06.51", "statusType": "slow", "statusText": "DISPLAY TERLALU LAMA"}
        assert app.ctl.result_visible and app.ui.names()[-1] == "show_result" and app.ctl.on_back() is True

    def test_tanpa_jeda_tepat_waktu(self, app):
        finish_coach(app)
        for i in range(6):
            app.ctl.on_enter(i, "60"); app.svc.run_for(300000); app.ctl.next_lorong()
        r = self.hasil(app)
        assert (r["totalQty"], r["target"], r["actual"], r["gap"], r["percent"], r["statusType"], r["statusText"]) == \
               ("360", "30:00", "30:00", "00:00", "+0.0%", "good", "BAGUS, DISPLAY TEPAT WAKTU")

    def test_qty_desimal_dan_ribuan(self, app):
        finish_coach(app)
        play(app, [1000, 250.5, 3, 7, 12, 99.9], press=0, enter=0)
        assert self.hasil(app)["totalQty"] == "1.372,4"                                   # titik ribuan, koma desimal (id-ID)

    def test_ok_mengosongkan_sesi_dan_mulai_lagi(self, app):
        finish_coach(app)
        play(app, [12] * 6)
        app.ui.calls.clear()
        app.ctl.result_ok()
        assert app.ui.names() == ["hide_result", "render_list", "set_stepper"] and app.ui.last("render_list")[1:] == (0, [None] * 6, [False] * 6)
        assert app.st.get(L.SESSION_KEY) is None and not app.ctl.result_visible
        app.svc.run_for(150)
        assert app.ui.last("focus_input") == ("focus_input", 0)
        assert app.ctl.on_enter(0, "12") is True and app.ctl.session.session_start_ms == app.svc.t   # sesi kedua mulai bersih

    def test_tombol_kembali_ditahan_saat_timer_dan_hasil(self, app):
        finish_coach(app)
        assert app.ctl.on_back() is False                                                 # layar utama: biasa (keluar)
        app.ctl.on_enter(0, "12")
        assert app.ctl.on_back() is True
        app.svc.run_for(60000); app.ctl.next_lorong()
        assert app.ctl.on_back() is False

    def test_menu_membersihkan_timer_dan_membuka_server(self, app):
        finish_coach(app)
        app.st.set(L.TIMER_KEY, "x")
        app.ctl.menu()
        assert app.st.get(L.TIMER_KEY) is None and app.ui.last("ask_server_url") == ("ask_server_url", "")


class TestMenuServer:
    def test_pertama_kali_minta_alamat_lalu_simpan_dan_buka(self, app):
        finish_coach(app)
        app.ctl.menu()
        assert app.svc.opened == []
        assert app.ui.server_cb("tidak valid pakai spasi") is False and app.ui.last("alert")[1].startswith("Alamat tidak valid") and app.st.get(L.SERVER_KEY) is None
        assert app.ui.server_cb("   ") is False
        assert app.ui.server_cb("domain.com/timer/") is True
        assert app.st.get(L.SERVER_KEY) == "https://domain.com/timer/" and app.svc.opened == ["https://domain.com/timer/menu.html"]

    def test_berikutnya_langsung_buka_dan_ubah_alamat_dengan_tekan_lama(self, app):
        finish_coach(app)
        app.st.set(L.SERVER_KEY, "https://a.com/x/")
        app.ctl.menu()
        assert app.svc.opened == ["https://a.com/x/menu.html"] and "ask_server_url" not in app.ui.names()
        app.ctl.edit_server()
        assert app.ui.server_prefill == "https://a.com/x/"
        app.ui.server_cb("https://b.com/y/index.html")
        assert app.svc.opened[-1] == "https://b.com/y/menu.html" and app.st.get(L.SERVER_KEY) == "https://b.com/y/index.html"

    def test_gagal_membuka_browser_dilaporkan(self, app):
        finish_coach(app)
        app.st.set(L.SERVER_KEY, "https://a.com/")
        app.svc.open_error = RuntimeError("tidak ada browser")
        app.ctl.menu()
        assert app.ui.last("alert")[1] == "Tidak dapat membuka browser: tidak ada browser"


class TestCoach:
    def test_dua_langkah_lalu_selesai_dan_tidak_muncul_lagi(self, app):
        app.ctl.init_app(); app.svc.run_for(1200)
        assert app.ui.last("show_coach") == ("show_coach", "Tombol MENU digunakan untuk membuka navigasi aplikasi lainnya.", False)
        app.ctl.next_coach()
        assert app.ui.last("show_coach") == ("show_coach", "Masukkan QTY barang di sini, lalu tekan ENTER untuk memulai timer.", True)
        assert app.ctl.on_back() is True                                                  # tutorial tampil: Kembali ditahan
        app.ctl.next_coach()
        assert app.ui.last("hide_coach") and app.st.get(L.COACH_KEY) == "true" and app.ui.last("focus_input") == ("focus_input", 0) and not app.ctl.on_back()
        ui2, svc2 = FakeUI(), FakeSvc()
        ctl2 = main.Controller(ui2, app.st, svc2)
        ctl2.init_app(); svc2.run_for(1200)
        assert "show_coach" not in ui2.names() and ui2.last("focus_input") == ("focus_input", 0)

    def test_target_hilang_dilewati(self, app):
        app.ui.targets["btn_menu"] = None
        app.ctl.init_app(); app.svc.run_for(1200)
        assert app.ui.of("show_coach")[0][1].startswith("Masukkan QTY") and app.ctl.coach_step == 1
        app.ui.targets["input_0"] = None
        ctl = main.Controller(app.ui, L.MemStorage(), app.svc)
        ctl.show_coach_step()
        assert ctl.storage.get(L.COACH_KEY) == "true"


# ===================================================== 5. layanan platform
@contextlib.contextmanager
def fake_modules(mods):
    old = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def android_fakes():
    log = SimpleNamespace(flags=[], intents=[])
    window = SimpleNamespace(addFlags=lambda f: log.flags.append(("add", f)), clearFlags=lambda f: log.flags.append(("clear", f)))
    activity = SimpleNamespace(getWindow=lambda: window, startActivity=lambda i: log.intents.append(i))

    class Intent:
        ACTION_VIEW = "android.intent.action.VIEW"
        def __init__(self, action, uri): self.action, self.uri = action, uri

    def autoclass(name):
        return {"org.kivy.android.PythonActivity": SimpleNamespace(mActivity=activity),
                "android.view.WindowManager$LayoutParams": SimpleNamespace(FLAG_KEEP_SCREEN_ON=128),
                "android.content.Intent": Intent, "android.net.Uri": SimpleNamespace(parse=lambda s: ("uri", s))}[name]
    mods = {"jnius": SimpleNamespace(autoclass=autoclass), "android": types.ModuleType("android"),
            "android.runnable": SimpleNamespace(run_on_ui_thread=lambda f: f)}
    return log, mods


class TestServices:
    def test_layar_tetap_menyala_hanya_di_android(self, tmp_path, monkeypatch):
        svc = main.Services(tmp_path)
        assert svc.keep_screen_on(True) is False                                         # desktop: tidak berbuat apa-apa
        log, mods = android_fakes()
        monkeypatch.setattr(main, "platform", "android")
        with fake_modules(mods):
            assert svc.keep_screen_on(True) is True and svc.keep_screen_on(False) is True
        assert log.flags == [("add", 128), ("clear", 128)]                                # FLAG_KEEP_SCREEN_ON dipasang lalu dilepas
        assert svc.keep_screen_on(True) is False                                          # tanpa jnius: gagal senyap, tidak crash

    def test_buka_alamat_android_dan_desktop(self, tmp_path, monkeypatch):
        svc = main.Services(tmp_path)
        seen = []
        monkeypatch.setattr(main.webbrowser, "open", lambda u: seen.append(u))
        svc.open_url("https://a.com/menu.html")
        assert seen == ["https://a.com/menu.html"]
        log, mods = android_fakes()
        monkeypatch.setattr(main, "platform", "android")
        with fake_modules(mods):
            svc.open_url("https://a.com/menu.html")
        assert len(log.intents) == 1 and log.intents[0].action == "android.intent.action.VIEW" and log.intents[0].uri == ("uri", "https://a.com/menu.html")

    def test_beep_membuat_wav_sekali_dan_memutarnya(self, tmp_path):
        played = []

        class Sound:
            def stop(self): played.append("stop")
            def play(self): played.append("play")
        loaded = []
        audio = SimpleNamespace(SoundLoader=SimpleNamespace(load=lambda p: loaded.append(p) or Sound()))
        svc = main.Services(tmp_path)
        with fake_modules({"kivy.core.audio": audio}):
            svc.beep(); svc.beep()
        assert played == ["stop", "play", "stop", "play"] and len(loaded) == 1
        assert (tmp_path / "beep.wav").exists() and wave.open(str(tmp_path / "beep.wav")).getnframes() > 10000

    def test_beep_gagal_tidak_menjatuhkan_aplikasi(self, tmp_path):
        audio = SimpleNamespace(SoundLoader=SimpleNamespace(load=lambda p: (_ for _ in ()).throw(RuntimeError("audio mati"))))
        with fake_modules({"kivy.core.audio": audio}):
            main.Services(tmp_path).beep()                                                # tidak melempar
        audio2 = SimpleNamespace(SoundLoader=SimpleNamespace(load=lambda p: None))
        with fake_modules({"kivy.core.audio": audio2}):
            main.Services(tmp_path).beep()

    def test_penjadwal_membungkus_clock_kivy(self, tmp_path):
        clock = sys.modules["kivy.clock"].Clock
        clock.events.clear()
        svc, hits = main.Services(tmp_path), []
        ev = svc.every(0.2, lambda: hits.append("tick")); svc.later(0.7, lambda: hits.append("late"))
        for e in list(clock.events):
            e.fn(0.016)
        assert hits == ["tick", "late"] and [e.t for e in clock.events] == [0.2, 0.7]
        svc.cancel(None); svc.cancel(ev)


# ===================================================== 6. kesesuaian tampilan & kode dengan HTML asli
ORIGINAL_TEXTS = [
    "TIMER MAXDIS", "Isi Qty lalu tekan ENTER untuk mulai timer.", "REFRESH SAAT TIMER BERJALAN AKAN MERESET LORONG YANG SEDANG DIKERJAKAN.",
    "Detail Lorong", "Qty", "Status", "Input", "Proses", "Selesai", "TIMER AKTIF", "Sedang mengerjakan...", "WAKTU TERSISA",
    "LANJUT LORONG BERIKUTNYA", "SELURUH LORONG SELESAI", "Seluruh lorong sudah dikerjakan. Berikut hasil pengerjaan pada sesi ini.",
    "Total Qty", "Shift", "Waktu Standar", "Waktu Kerja", "Total Gap", "Waktu Aktual", "Deviasi", "Waktu Selesai",
    "Waktu aktual dihitung dari mulai Lorong 1 sampai Lorong terakhir selesai. Gap antar-lorong ikut dihitung. Rentang -10% sampai +10% dianggap tepat waktu.",
    "LOAD APLIKASI...", "Tombol MENU digunakan untuk membuka navigasi aplikasi lainnya.", "Masukkan QTY barang di sini, lalu tekan ENTER untuk memulai timer.",
    "Mulai Kerja!", "Lanjut", "Hampir selesai!", "30 detik terakhir.", "Tinggal sebentar lagi.", "Waktu berjalan.", "WAKTU HABIS!",
    "Masukkan Qty lebih dari 0.", "DISPLAY TERLALU CEPAT", "BAGUS, DISPLAY TEPAT WAKTU", "DISPLAY TERLALU LAMA", "DATA WAKTU BELUM CUKUP",
    "DI LUAR SHIFT", "SHIFT 1", "SHIFT 2", "SHIFT 3", "LORONG 1", "LORONG 6", "L01", "L06", "MENU", "TIMER",
    "timerMaxdisState", "timerMaxdisSession", "timerMaxdisCoachDone", "./menu.html"]


class TestFidelity:
    def test_semua_teks_asli_ada(self):
        src = MAIN_SRC + LOGIC_SRC
        missing = [t for t in ORIGINAL_TEXTS if t not in src]
        assert not missing, missing

    def test_konstanta_asli(self):
        assert L.LORONG == [("L0%d" % i, "LORONG %d" % i) for i in range(1, 7)]
        assert (main.SPLASH_SHOW_S, main.SPLASH_FADE_S, main.FOCUS_DELAY_S, main.TICK_S, main.ALARM_S) == (0.7, 0.4, 0.15, 0.2, 1.0)
        assert "(qty / 12) * 60" in LOGIC_SRC and "(total_qty / 60) * 5 * 60" in LOGIC_SRC

    def test_stepper_dan_warna_status(self):
        assert re.findall(r"'(\w*)', '(\w*)', '(\w*)'|\((\"active\"|\"done\"|\"\"), (\"active\"|\"done\"|\"\"), (\"active\"|\"done\"|\"\")\)", MAIN_SRC)
        for color in ("0.898, 0.106, 0.137", "0, 0.369, 0.667", "0.298, 0.686, 0.314"):    # #e51b23, #005eaa, #4caf50
            assert color in main.KV


# ===================================================== 7. pemeriksaan statis KV
def kv_block(rule):
    m = re.search(r"^<%s>:\n(.*?)(?=^<|\Z)" % re.escape(rule), main.KV, re.S | re.M)
    assert m, rule
    return m.group(1)


class TestStatic:
    def test_sintaks_dan_indentasi_kv(self):
        compile(MAIN_SRC, "main.py", "exec"); compile(LOGIC_SRC, "logic.py", "exec")
        for n, line in enumerate(main.KV.splitlines(), 1):
            assert "\t" not in line and (not line.strip() or (len(line) - len(line.lstrip())) % 4 == 0), "KV baris %d" % n

    def test_kelas_kv_dikenal_tanpa_pewarisan_dinamis(self):
        for cls in re.findall(r"^<(\w+)>:", main.KV, re.M):
            assert hasattr(main, cls), cls
        dynamic = dict(re.findall(r"^<(\w+)@(\w+)>:", main.KV, re.M))
        builtin = {"BoxLayout", "FloatLayout", "Widget", "Button", "Label", "TextInput", "ScrollView", "GridLayout", "AnchorLayout"}
        for name, base in dynamic.items():
            assert base in builtin, (name, base)                                           # pola terbukti: tanpa pewarisan antar-kelas dinamis
        known = set(dynamic) | {c for c in re.findall(r"^<(\w+)>:", main.KV, re.M)} | builtin | {"Color", "Rectangle", "RoundedRectangle", "Ellipse", "Line"}
        for w in set(re.findall(r"^\s+([A-Z]\w+):\s*$", main.KV, re.M)):
            assert w in known or hasattr(main, w), w                                       # kelas widget Python (MenuButton, LorongRow, ...)

    def test_id_python_cocok_dengan_kv(self):
        root_ids = set(re.findall(r"^\s+id:\s*(\w+)", kv_block("RootView"), re.M))
        assert {"rows", "s1", "s2", "s3", "btn_menu"} <= root_ids
        for m in set(re.findall(r"self\.ids\.(\w+)", MAIN_SRC)):
            assert m in root_ids | {"field"}, m
        assert {"dot", "belt"} <= set(re.findall(r"^\s+id:\s*(\w+)", kv_block("TimerOverlay"), re.M))
        rv = set(re.findall(r"^\s+id:\s*(\w+)", kv_block("ResultView"), re.M))
        assert {"status", "qty", "shift", "target", "work", "gap", "actual", "percent", "finished"} <= rv
        assert "field" in set(re.findall(r"^\s+id:\s*(\w+)", kv_block("LorongRow"), re.M))
        assert not (set(re.findall(r"^\s+id:\s*(\w+)", main.KV, re.M)) & {"root", "self", "app"})

    def test_rujukan_app_dan_controller_ada(self):
        for m in set(re.findall(r"\bapp\.(\w+)", main.KV)):
            assert m == "controller" or hasattr(main.TimerMaxdisApp, m), m
        for m in set(re.findall(r"app\.controller\.(\w+)", main.KV)):
            assert hasattr(main.Controller, m), m
        for cls in ("LorongRow",):
            for m in set(re.findall(r"\broot\.(\w+)\(", kv_block(cls))):
                assert hasattr(getattr(main, cls), m), m

    def test_status_hasil_memakai_properti_yang_dideklarasikan_di_kelas_dinamis(self):
        block = re.search(r"^<StatusBox@BoxLayout>:\n(.*?)(?=^<)", main.KV, re.S | re.M).group(1)
        assert "kind:" in block and "text:" in block and "id: status" in kv_block("ResultView") and "StatusBox:" in kv_block("ResultView")
        assert "root.ids.status" not in main.KV and "Panel:\n                id: status" not in main.KV   # properti buatan di blok instance dihindari

    def test_struktur_kv_indentasi_naik_maksimal_satu_tingkat_dan_kurung_seimbang(self):
        prev = 0
        for n, line in enumerate(main.KV.splitlines(), 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            ind = len(line) - len(line.lstrip())
            assert ind <= prev + 4, "indentasi melompat di baris KV %d: %r" % (n, line)
            assert line.count("(") == line.count(")") and line.count("[") == line.count("]"), "kurung tak seimbang di baris KV %d" % n
            prev = ind

    def test_setiap_properti_kv_punya_nilai(self):
        for n, line in enumerate(main.KV.splitlines(), 1):
            s = line.strip()
            if re.fullmatch(r"[a-z_][\w.]*:", s) and s[:-1] not in ("canvas", "canvas.before", "canvas.after"):
                assert False, "properti tanpa nilai di baris KV %d: %r" % (n, s)


# ===================================================== 8. pengemasan
def spec():
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(HERE / "buildozer.spec", encoding="utf-8")
    return cp["app"]


class TestPackaging:
    def test_buildozer_spec(self):
        a = spec()
        reqs = {r.strip().split("==")[0] for r in a["requirements"].split(",")}
        assert reqs == {"python3", "kivy", "pyjnius", "android"}                            # tanpa paket tambahan: build paling andal
        assert re.fullmatch(r"[a-z][a-z0-9]*", a["package.name"]) and (HERE / "main.py").exists() and (HERE / "logic.py").exists()
        assert a["android.permissions"].strip() == "" and a["orientation"] == "portrait"
        assert a["android.accept_sdk_license"].lower() == "true" and a["android.release_artifact"] == "apk"
        assert {"test_*.py", "tools/*"} <= {x.strip() for x in a["source.exclude_patterns"].split(",")} and "py" in a["source.include_exts"]
        assert a["p4a.branch"] == "v2024.01.21" and a["android.ndk"] == "25b" and a["android.api"] == "33"   # alat build terbukti
        assert "kivy==2.3.0" in a["requirements"] and a["android.archs"] == "arm64-v8a"

    def test_impor_pihak_ketiga_ada_di_requirements(self):
        names = set()
        for src in (MAIN_SRC, LOGIC_SRC):
            for n in ast.walk(ast.parse(src)):
                if isinstance(n, ast.Import):
                    names |= {x.name.split(".")[0] for x in n.names}
                if isinstance(n, ast.ImportFrom) and n.level == 0:
                    names.add(n.module.split(".")[0])
        local = {p.stem for p in HERE.glob("*.py")}
        third = {{"jnius": "pyjnius"}.get(n, n) for n in names if n not in sys.stdlib_module_names and n not in local}
        reqs = {r.strip().split("==")[0] for r in spec()["requirements"].split(",")}
        assert third and third <= reqs, third - reqs

    def test_workflow_github_actions(self):
        try:
            import yaml
        except ImportError:
            return
        text = (HERE / ".github" / "workflows" / "build-apk.yml").read_text(encoding="utf-8")
        wf = yaml.safe_load(text)
        on = wf.get("on", wf.get(True))
        assert "v*" in on["push"]["tags"] and "workflow_dispatch" in on and wf["permissions"]["contents"] == "write"
        assert set(wf["jobs"]) == {"test", "build"} and wf["jobs"]["build"]["needs"] == "test"
        for token in ("buildozer -v android debug", "libltdl-dev", "libffi-dev", "pytest -v test_main.py", "tee -a build.log", "GITHUB_STEP_SUMMARY", "Command failed"):
            assert token in text, token
        steps = wf["jobs"]["build"]["steps"]
        by = {x.get("name", ""): x for x in steps}
        assert by["Ringkasan penyebab error (hanya bila gagal)"]["if"] == "failure()"
        rest = next(x for x in steps if x.get("uses", "").startswith("actions/cache/restore"))
        assert all("p4a2024" in k for k in [rest["with"]["key"]] + rest["with"]["restore-keys"].strip().splitlines())

    def test_readme_dan_berkas_uji(self):
        r = (HERE / "README.md").read_text(encoding="utf-8")
        for token in ("golden.json", "menu.html", "MENU", "Run workflow", "display.mp4", "Node.js"):
            assert token in r, token
        assert GOLDEN_PATH.stat().st_size > 100000 and (HERE / "tools" / "reference.js").exists() and (HERE / "tools" / "gen_golden.js").exists()


# ===================================================== 9. kinerja
class TestPerformance:
    def test_ribuan_tick_dan_sesi_cepat(self):
        t0 = time.perf_counter()
        for i in range(20000):
            L.tick_info(60000, 60, i * 3)
        for i in range(300):
            st = L.MemStorage(); s = L.TimerSession(st); tt = T0
            for k in range(6):
                s.now = lambda v=tt: v; s.start_timer(10 + k); tt += 50000; s.now = lambda v=tt: v; s.finish_timer(); s.finish_lorong(); tt += 3000
            assert s.result()["statusType"] in ("good", "slow", "fast")
        assert time.perf_counter() - t0 < 5
