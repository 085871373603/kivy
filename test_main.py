"""
Pengujian Stock Opname  ->  pytest -v test_main.py

Kivy diganti stub ringan sehingga seluruh logika (perhitungan, penyimpanan lokal, klien Firebase
terhadap SERVER HTTP PALSU sungguhan, pembuat PNG, alur layar) diuji otomatis tanpa layar.
Tampilan KV diperiksa secara statis; render visual diuji manual di HP.
"""
import ast
import configparser
import http.server
import json
import random
import re
import socket
import struct
import sys
import threading
import time
import types
import urllib.parse
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

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
        def open(self): pass
        def dismiss(self):
            for cb in self._binds.get("on_dismiss", []):
                cb(self)

    class Ev:
        def __init__(self, fn): self.fn, self.cancelled = fn, False
        def cancel(self): self.cancelled = True

    class Clock:
        events = []
        @staticmethod
        def schedule_once(fn, t=0):
            e = Ev(fn); Clock.events.append(e); return e

    class App:
        running = None
        @classmethod
        def get_running_app(cls): return cls.running

    def escape_markup(t):  # identik dengan kivy.utils.escape_markup
        return t.replace("&", "&amp;").replace("[", "&bl;").replace("]", "&br;")

    for n in ("kivy", "kivy.uix", "kivy.core"):
        mod(n); sys.modules[n].__path__ = []
    mod("kivy.app", App=App)
    mod("kivy.clock", Clock=Clock)
    mod("kivy.core.window", Window=SimpleNamespace(width=480, size=(480, 800), clearcolor=None, bind=lambda **k: None))
    mod("kivy.lang", Builder=SimpleNamespace(load_string=lambda s: None))
    mod("kivy.metrics", dp=lambda x: x, sp=lambda x: x)
    for n, c in (("boxlayout", "BoxLayout"), ("button", "Button"), ("label", "Label"), ("popup", "Popup"),
                 ("textinput", "TextInput")):
        mod("kivy.uix." + n, **{c: type(c, (W,), {})})
    mod("kivy.uix.screenmanager", Screen=type("Screen", (W,), {}), ScreenManager=type("SM", (W,), {}))
    mod("kivy.utils", escape_markup=escape_markup, platform="linux")


_install_kivy_stub()
import main  # noqa: E402

SOURCE = Path(main.__file__).read_text(encoding="utf-8")
ORIG_RUN_ASYNC = main.run_async
CLOCK = sys.modules["kivy.clock"].Clock
PRODUCTS = [("8991001", "Susu UHT Coklat 200ml", 24), ("8991002", "Teh Botol 450ml", 36),
            ("8991003", "Air Mineral 600ml", 120), ("12", "Kopi Bubuk 100g", 7.5), ("A.B/1", "Item Kode Khusus", 3)]


# ------------------------------------------------------------------- helpers
TAG = re.compile(r"\[(/?)(b|color)(=[0-9a-f]{6})?\]")


def valid_markup(s):
    """Markup Kivy sah: tak ada kurung liar / tag asing, tag seimbang, '&' ter-escape."""
    t = s.replace("&bl;", "").replace("&br;", "").replace("&amp;", "")
    if "&" in t:
        return False
    stack = []
    for tok in re.findall(r"\[[^\[\]]*\]|[\[\]]", t):
        m = TAG.fullmatch(tok)
        if not m:
            return False
        if m.group(1):
            if not stack or stack.pop() != m.group(2):
                return False
        else:
            stack.append(m.group(2))
    return not stack


def seed(store, items=PRODUCTS):
    for p in items:
        store.upsert_product(*p)


def count_all(store, per_item):
    """per_item: {plu: [c1..c5]}"""
    for plu, c in per_item.items():
        store.set_counts(plu, c)


def mk_session(items, status="final"):
    return {"id": "SO-TEST", "created": "2026-01-01 08:00:00", "status": status,
            "finalized": "2026-01-01 09:30:00" if status == "final" else None,
            "items": [{"plu": p, "desc": d, "oh": o, "counts": c} for p, d, o, c in items]}


class F:
    """Widget palsu untuk ids layar."""
    def __init__(self, **kw):
        self.__dict__.update(dict(text="", disabled=False, readonly=False, focus=False, active=False, scroll_y=1), **kw)
        self.data = []
    def refresh_from_data(self): pass


def kv_block(rule):
    return re.search(r"^<%s>:\n(.*?)(?=^<|\Z)" % re.escape(rule), main.KV, re.S | re.M).group(1)


def ids_of(rule):
    return set(re.findall(r"^\s+id:\s*(\w+)", kv_block(rule), re.M))


def screen(cls):
    s = cls()
    s.ids = SimpleNamespace(**{i: F() for i in ids_of(cls.__name__)})
    return s


def sync_run(fn, cb):
    try:
        res, err = fn(), None
    except Exception as e:  # noqa: BLE001
        res, err = None, e
    cb(res, err)


@pytest.fixture
def env(tmp_path, monkeypatch):
    store = main.Store(tmp_path / "data")
    monkeypatch.setattr(main, "STORE", store)
    pops = []
    monkeypatch.setattr(main, "popup", lambda title, msg, buttons, height=0: pops.append(
        SimpleNamespace(title=title, msg=msg, btn={b[0]: b[1] for b in buttons})))
    monkeypatch.setattr(main, "run_async", sync_run)
    nav = SimpleNamespace(root=SimpleNamespace(current="home"), sync_status="")
    sys.modules["kivy.app"].App.running = nav
    CLOCK.events.clear()
    main.OPEN_POPUPS.clear()
    return SimpleNamespace(store=store, pops=pops, nav=nav, tmp=tmp_path)


@pytest.fixture
def seeded(env):
    seed(env.store)
    return env


@pytest.fixture
def running(seeded):
    """Sesi berjalan berisi 3 item: 8991001 (OH 24), 8991002 (OH 36), 12 (OH 7.5)."""
    seeded.store.apply_setup(["8991001", "8991002", "12"])
    return seeded


# ------------------------------------------------ server Firebase palsu (HTTP sungguhan)
class FakeRTDB:
    """Meniru Realtime Database REST: .json, auth, PUT/GET/PATCH/DELETE, print=silent, kunci terlarang -> 400."""
    BAD = re.compile(r"[.$#\[\]]")

    def __init__(self, secret="rahasia"):
        self.secret, self.data, self.log, self.fail, self.saw_list = secret, {}, [], None, False
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def send(self, code, obj=None):
                body = b"" if code == 204 else json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def handle_any(self):
                u = urllib.parse.urlsplit(self.path)
                q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                outer.log.append((self.command, urllib.parse.unquote(u.path), q))
                if outer.fail:
                    return self.send(outer.fail, {"error": "simulasi"})
                if not u.path.endswith(".json"):
                    return self.send(404, {"error": "bukan .json"})
                if outer.secret and q.get("auth") != outer.secret:
                    return self.send(401, {"error": "Permission denied"})
                segs = [x for x in urllib.parse.unquote(u.path[1:-5]).split("/") if x]
                if any(outer.BAD.search(s) for s in segs):
                    return self.send(400, {"error": "Invalid path"})
                silent = q.get("print") == "silent"
                if self.command == "GET":
                    return self.send(200, outer.get(segs))
                body = json.loads(raw.decode("utf-8")) if raw else None
                if self.command == "DELETE":
                    outer.put(segs, None)
                    return self.send(204 if silent else 200, None)
                if outer.bad_keys(body):
                    return self.send(400, {"error": "Invalid key"})
                outer.put(segs, body)
                return self.send(204 if silent else 200, body)

            do_GET = do_PUT = do_PATCH = do_DELETE = handle_any

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def bad_keys(self, v):
        return isinstance(v, dict) and any(self.BAD.search(k) or self.bad_keys(x) for k, x in v.items())

    def clean(self, v):
        if isinstance(v, list):
            self.saw_list = True
        if isinstance(v, dict):
            v = {k: self.clean(x) for k, x in v.items() if x is not None}
            return {k: x for k, x in v.items() if x != {}} or None
        return v

    def get(self, segs):
        node = self.data
        for s in segs:
            if not isinstance(node, dict) or s not in node:
                return None
            node = node[s]
        return node

    def put(self, segs, val):
        val = self.clean(val)
        if not segs:
            self.data = val or {}
            return
        node = self.data
        for s in segs[:-1]:
            if not isinstance(node.get(s), dict):
                node[s] = {}
            node = node[s]
        if val is None:
            node.pop(segs[-1], None)
        else:
            node[segs[-1]] = val
        self.prune(self.data)

    def prune(self, node):
        """Firebase tidak menyimpan objek kosong: node induk yang kosong ikut hilang."""
        for k in list(node):
            if isinstance(node[k], dict):
                self.prune(node[k])
                if not node[k]:
                    del node[k]


@pytest.fixture
def fake_db():
    db = FakeRTDB()
    yield db
    db.stop()


def fb(db, **kw):
    return main.Firebase(db.url, kw.pop("root", "stockopname"), kw.pop("auth", db.secret), timeout=5, **kw)


def decode_png(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, chunks = 8, b"", {}
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        t, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        assert struct.unpack(">I", data[pos + 8 + n:pos + 12 + n])[0] == zlib.crc32(t + body) & 0xFFFFFFFF
        if t == b"IDAT":
            idat += body
        else:
            chunks[t] = body
        pos += 12 + n
    w, h, depth, ctype, comp, filt, inter = struct.unpack(">IIBBBBB", chunks[b"IHDR"])
    assert (depth, ctype, comp, filt, inter) == (8, 2, 0, 0, 0) and b"IEND" in chunks
    raw = zlib.decompress(idat)
    stride = w * 3 + 1
    assert len(raw) == h * stride
    rows = []
    for y in range(h):
        assert raw[y * stride] == 0
        rows.append(raw[y * stride + 1:(y + 1) * stride])
    return w, h, rows


def px(rows, x, y):
    return tuple(rows[y][x * 3:x * 3 + 3])


def lay():
    f = main._font()
    cw, ch = f["w"], f["h"]
    xs, acc = [], main.REPORT_PAD
    for _, w in main.REPORT_COLS:
        xs.append(acc)
        acc += w
    return SimpleNamespace(cw=cw, ch=ch, pad=main.REPORT_PAD, row_h=2 * ch + 14, head_h=2 * ch + 40, th_h=ch + 18,
                           sum_h=2 * ch + 38, tot_h=ch + 24, xs=xs, cols=dict(main.REPORT_COLS))


# ===================================================== 1. pemeriksaan statis
class TestStatic:
    def test_sintaks(self):
        compile(SOURCE, "main.py", "exec")

    def test_kv_indentasi_rapi(self):
        for n, line in enumerate(main.KV.splitlines(), 1):
            assert "\t" not in line, "tab di baris KV %d" % n
            if line.strip():
                assert (len(line) - len(line.lstrip())) % 4 == 0, "indentasi baris KV %d" % n

    def test_id_kv_cocok_dengan_python(self):
        for cls in ("HomeScreen", "ProductsScreen", "SetupScreen", "SOScreen", "FirebaseScreen"):
            body = re.search(r"^class %s\(Screen\):\n(.*?)(?=^class |^KV = )" % cls, SOURCE, re.S | re.M).group(1)
            used = set(re.findall(r"self\.ids\.(\w+)", body))
            assert used <= ids_of(cls), (cls, used - ids_of(cls))

    def test_id_tidak_memakai_kata_kunci_kv(self):
        assert not (set(re.findall(r"^\s+id:\s*(\w+)", main.KV, re.M)) & {"root", "self", "app", "args"})

    def test_referensi_root_dan_app_ada(self):
        screens = [main.HomeScreen, main.ProductsScreen, main.SetupScreen, main.SOScreen, main.FirebaseScreen]
        for cls in screens:
            for m in set(re.findall(r"\broot\.(\w+)", kv_block(cls.__name__))):
                assert hasattr(cls, m), (cls.__name__, m)
        for m in set(re.findall(r"\bapp\.(\w+)", main.KV)):
            assert hasattr(main.StockOpnameApp, m), m

    def test_kelas_dan_widget_kv_dikenal(self):
        for cls in re.findall(r"^<(\w+)>:", main.KV, re.M):
            assert hasattr(main, cls), cls
        dynamic = set(re.findall(r"^<(\w+)@\w+>:", main.KV, re.M))
        builtin = {"BoxLayout", "ScrollView", "RecycleView", "RecycleBoxLayout", "Color", "Rectangle", "Line",
                   "Widget", "Label", "Button", "Switch"}
        for w in set(re.findall(r"^\s+([A-Z]\w+):\s*$", main.KV, re.M)):
            assert w in dynamic | builtin, w
        for vc in re.findall(r"viewclass:\s*'(\w+)'", main.KV):
            assert vc in dynamic, vc
        for name, base in re.findall(r"^<(\w+)@(\w+)>:", main.KV, re.M):                       # pola yang sudah terbukti di HP: tanpa pewarisan antar-kelas dinamis
            assert base not in dynamic, (name, base)
        assert "home.refresh()" in SOURCE                                                      # layar pertama dimuat eksplisit

    def test_target_navigasi_valid(self):
        screens = set(re.findall(r"^\s+name:\s*'(\w+)'", main.KV, re.M))
        assert screens == {"home", "products", "setup", "so", "firebase"}
        for t in set(re.findall(r"app\.go\('(\w+)'\)", main.KV)) | set(re.findall(r'go\("(\w+)"\)', SOURCE)):
            assert t in screens, t

    def test_menu_sesuai_permintaan(self):
        home = kv_block("HomeScreen")
        assert "GENERAL" in home and "Input SKU" in home and "Setting Item Stock Opname" in home
        assert home.index("GENERAL") < home.index("Input SKU") < home.index("Setting Item Stock Opname") < home.index("STOCK OPNAME")

    def test_header_tabel_sesuai_permintaan(self):
        head = re.search(r"<SOHeader@BoxLayout>:\n(.*?)(?=^<)", main.KV, re.S | re.M).group(1)
        assert re.findall(r"text:\s*'([^']*)'", head) == ["PLU / Deskripsi", "OH", "1", "2", "3", "4", "5", "Total", "Selisih"]
        assert "chr(10) + 'Fisik'" in head                                                 # "Total Fisik" dua baris

    def test_font_bitmap_konsisten(self):
        import base64
        import fontdata
        for data in (fontdata.REGULAR, fontdata.BOLD):
            assert len(zlib.decompress(base64.b64decode(data))) == 95 * fontdata.W * fontdata.H


# ====================================================== 2. angka & teks
class TestNumbers:
    @pytest.mark.parametrize("txt,val", [("", None), ("  ", None), ("0", 0.0), ("12", 12.0), ("2,5", 2.5), ("2.5", 2.5),
                                         (" 1 000 ", 1000.0), ("+3", 3.0), ("-4", -4.0), ("0,125", 0.125), ("999999999999", 999999999999.0)])
    def test_parse_qty_valid(self, txt, val):
        assert main.parse_qty(txt) == val

    @pytest.mark.parametrize("txt", ["abc", "1e3", "nan", "inf", "-inf", "1,2,3", "1.2.3", "--1", "1,2345", "12a", "0x10", "1000000000000"])
    def test_parse_qty_ditolak(self, txt):
        with pytest.raises(ValueError):
            main.parse_qty(txt)

    def test_negatif_ditolak_untuk_hitungan(self):
        with pytest.raises(ValueError, match="negatif"):
            main.parse_qty("-1", allow_negative=False)

    def test_fmt(self):
        assert [main.fmt_qty(v) for v in (None, 0, 5.0, 2.5, 0.125, 1000, -3, 0.1 + 0.2)] == ["", "0", "5", "2.5", "0.125", "1000", "-3", "0.3"]
        assert [main.fmt_diff(v) for v in (None, 0, 3, -2, 1.5)] == ["", "0", "+3", "-2", "+1.5"]

    def test_filter_input(self):
        assert main.qty_filter("a1b,2.-c", False) == "1,2."
        assert main.oh_filter("a-1b,2", False) == "-1,2"

    def test_urutan_alami_dan_normalisasi(self):
        assert sorted(["10", "2", "A1", "1"], key=main.natkey) == ["1", "2", "10", "A1"]
        assert main.norm_plu("  ab  12 ") == "AB 12" and main.norm_plu(None) == ""


# ====================================================== 3. Input SKU (produk)
class TestProducts:
    def test_tambah_ubah_dan_validasi(self, env):
        p, created = env.store.upsert_product(" 899 1 ", "  Susu   UHT ", "12,5")
        assert created and p["plu"] == "899 1" and p["desc"] == "Susu UHT" and p["oh"] == 12.5
        p2, created2 = env.store.upsert_product("899 1", "Susu UHT Baru", 20)
        assert not created2 and env.store.products()["899 1"]["oh"] == 20 and len(env.store.products()) == 1
        for args, msg in [(("", "x", "1"), "PLU wajib"), (("a", "", "1"), "Deskripsi wajib"), (("a", "x", ""), "wajib diisi"),
                          (("a", "x", "abc"), "angka"), (("a" * 41, "x", "1"), "40"), (("a", "x" * 121, "1"), "120")]:
            with pytest.raises(ValueError, match=msg):
                env.store.upsert_product(*args)
        assert len(env.store.products()) == 1  # yang ditolak tidak tersimpan

    def test_oh_nol_dan_negatif_diizinkan(self, env):
        assert env.store.upsert_product("a", "x", "0")[0]["oh"] == 0
        assert env.store.upsert_product("b", "x", "-2")[0]["oh"] == -2

    def test_plu_ganda_tanpa_izin_update(self, env):
        env.store.upsert_product("a", "x", 1)
        with pytest.raises(ValueError, match="sudah ada"):
            env.store.upsert_product("A", "y", 2, allow_update=False)
        assert env.store.products()["A"]["desc"] == "x"

    def test_hapus_dan_cari_dan_urutan(self, seeded):
        st = seeded.store
        assert [p["plu"] for p in st.product_list()] == ["12", "8991001", "8991002", "8991003", "A.B/1"]
        assert [p["plu"] for p in st.product_list("TEH")] == ["8991002"] and [p["plu"] for p in st.product_list("8991")] == ["8991001", "8991002", "8991003"]
        assert st.delete_product("8991002") and not st.delete_product("tidak-ada") and len(st.products()) == 4

    def test_tersimpan_permanen_dan_atomik(self, seeded):
        again = main.Store(seeded.store.base)                      # "buka-ulang aplikasi"
        assert again.products() == seeded.store.products() and len(again.products()) == 5
        assert not list(seeded.store.base.glob("*.tmp"))

    def test_berkas_rusak_tidak_membuat_crash(self, env):
        (env.store.base / "products.json").write_text("{rusak", encoding="utf-8")
        assert main.Store(env.store.base).products() == {}
        (env.store.base / "products.json").write_text('{"X": {"plu": "X"}, "Y": 5, "Z": {"plu":"Z","desc":"ok","oh":1}}', encoding="utf-8")
        assert list(main.Store(env.store.base).products()) == ["Z"]

    def test_merge(self, seeded):
        n = seeded.store.merge_products({"8991001": {"plu": "8991001", "desc": "Baru", "oh": 1.0, "updated": ""}, "ZZ": {"plu": "ZZ", "desc": "Z", "oh": 2.0, "updated": ""}})
        assert n == 2 and seeded.store.products()["8991001"]["desc"] == "Baru" and "8991002" in seeded.store.products() and "ZZ" in seeded.store.products()


# ====================================================== 4. Setting item SO & sesi
class TestSetup:
    def test_setup_membuat_sesi_dengan_snapshot(self, seeded):
        s = seeded.store.apply_setup(["8991002", "12", "tidak-ada", "12"])
        assert re.fullmatch(r"SO-\d{8}-\d{6}", s["id"]) and s["status"] == "open"
        assert [(i["plu"], i["oh"], i["counts"]) for i in s["items"]] == [("12", 7.5, [None] * 5), ("8991002", 36, [None] * 5)]
        assert seeded.store.session() == s

    def test_setup_kosong_ditolak(self, seeded):
        with pytest.raises(ValueError, match="minimal 1"):
            seeded.store.apply_setup([])
        with pytest.raises(ValueError):
            seeded.store.apply_setup(["tidak-ada"])
        assert seeded.store.session() is None

    def test_hasil_hitung_dipertahankan_saat_setup_ulang(self, running):
        st = running.store
        sid = st.session()["id"]
        st.set_counts("8991001", [10, 5])
        st.upsert_product("8991001", "Susu UHT Coklat 200ml", 30)    # OH diubah di data produk
        s = st.apply_setup(["8991001", "8991003"])                    # 8991002 & 12 keluar, 8991003 masuk
        assert s["id"] == sid and [i["plu"] for i in s["items"]] == ["8991001", "8991003"]
        assert s["items"][0]["counts"] == [10, 5, None, None, None] and s["items"][0]["oh"] == 30   # OH diperbarui, hitungan tetap
        assert s["items"][1]["counts"] == [None] * 5

    def test_setup_setelah_final_memulai_sesi_baru(self, running):
        st = running.store
        count_all(st, {"8991001": [1], "8991002": [2], "12": [3]})
        old = st.finalize()
        time.sleep(1.1)
        new = st.apply_setup(["8991001"])
        assert new["id"] != old["id"] and new["status"] == "open" and new["items"][0]["counts"] == [None] * 5
        assert (st.history_dir / (old["id"] + ".json")).exists()      # sesi final lama tetap di riwayat


# ====================================================== 5. perhitungan hitungan fisik
class TestCounting:
    def test_rumus_total_dan_selisih(self):
        it = {"oh": 24, "counts": [10, 5, None, 7, None]}
        assert main.item_calc(it) == (True, 22.0, -2.0)                    # total = 1+2+3+4+5, selisih = total - OH
        assert main.item_calc({"oh": 5, "counts": [None] * 5}) == (False, None, None)
        assert main.item_calc({"oh": 5, "counts": [0, None, None, None, None]}) == (True, 0.0, -5.0)   # 0 = sudah dihitung
        assert main.item_calc({"oh": 10, "counts": [2, 2, 2, 2, 2]}) == (True, 10.0, 0.0)
        assert main.item_calc({"oh": 1, "counts": [0.1, 0.2, None, None, None]})[1:] == (0.3, -0.7)   # tanpa galat desimal
        assert main.item_calc({"oh": -3, "counts": [1, None, None, None, None]})[2] == 4.0

    def test_set_counts_dan_validasi(self, running):
        st = running.store
        it = st.set_counts("8991001", [10, 5, None, 7])
        assert it["counts"] == [10, 5, None, 7, None] and st.item("8991001")["counts"] == it["counts"]
        for bad in ([-1], [float("nan")], [float("inf")], ["5"], [True], [1, 2, 3, 4, 5, 6]):
            with pytest.raises(ValueError):
                st.set_counts("8991001", bad)
        with pytest.raises(ValueError, match="tidak ada"):
            st.set_counts("8991003", [1])                                  # bukan item sesi
        assert st.item("8991001")["counts"] == [10, 5, None, 7, None]      # yang ditolak tidak mengubah data
        st.set_counts("8991001", [])                                       # kosongkan lagi
        assert not main.item_calc(st.item("8991001"))[0]

    def test_tanpa_sesi(self, env):
        with pytest.raises(ValueError, match="Belum ada setup"):
            env.store.set_counts("a", [1])

    def test_ringkasan(self, running):
        st = running.store
        count_all(st, {"8991001": [24], "8991002": [30, 5, 3], "12": [10]})     # sesuai, lebih(+2), ... lihat di bawah
        sm = main.summarize(st.session())
        # 8991001: 24-24=0 | 8991002: 38-36=+2 | 12: 10-7.5=+2.5
        assert sm == {"n": 3, "done": 3, "ok": 1, "short": 0, "over": 2, "oh_total": 67.5, "fisik_total": 72.0, "diff_total": 4.5}
        st.set_counts("12", [])
        assert main.summarize(st.session())["done"] == 2

    def test_finalisasi_butuh_semua_dihitung(self, running):
        st = running.store
        st.set_counts("8991001", [1])
        with pytest.raises(ValueError, match="2 produk belum dihitung"):
            st.finalize()
        assert st.session()["status"] == "open"
        count_all(st, {"8991002": [2], "12": [0]})
        s = st.finalize()
        assert s["status"] == "final" and s["finalized"] and s["summary"]["n"] == 3
        assert (st.history_dir / (s["id"] + ".json")).exists()
        with pytest.raises(ValueError, match="final"):
            st.set_counts("8991001", [9])                                  # terkunci setelah final
        with pytest.raises(ValueError):
            st.finalize()

    def test_buka_kembali_untuk_revisi(self, running):
        st = running.store
        count_all(st, {"8991001": [1], "8991002": [2], "12": [3]})
        st.finalize()
        s = st.reopen()
        assert s["status"] == "open" and s["finalized"] is None and "summary" not in s
        st.set_counts("12", [4])
        assert st.finalize()["items"][0]["counts"][0] == 4
        st.reopen()
        with pytest.raises(ValueError, match="belum final"):
            st.reopen()


# ====================================================== 6. Firebase: kunci & format
class TestFirebaseFormat:
    @pytest.mark.parametrize("plu", ["A.B/1", "8991001", "X$Y#Z[1]", "50%OFF", "a%2Eb", "kopi susu", "日本酒", "%", "...", "a/b/c"])
    def test_kunci_bolak_balik_dan_legal(self, plu):
        k = main.fb_key(plu)
        assert not re.search(r"[.$#\[\]/\x00-\x1f]", k) and main.fb_unkey(k) == plu

    def test_kunci_kosong_ditolak(self):
        with pytest.raises(ValueError):
            main.fb_key("")

    def test_sesi_bolak_balik_termasuk_hitungan_kosong(self, running):
        st = running.store
        st.set_counts("8991001", [10, None, 0, 7.5, None])
        s = st.session()
        back = main.session_from_fb(json.loads(json.dumps(main.session_to_fb(s))), s["id"])    # lewat JSON seperti di jaringan
        assert back["items"] == s["items"] and back["id"] == s["id"] and back["status"] == "open"

        def has_list(o):
            return isinstance(o, list) or (isinstance(o, dict) and any(has_list(v) for v in o.values()))
        assert not has_list(main.session_to_fb(s))                                               # hitungan kosong tak boleh jadi array

    def test_sesi_final_membawa_ringkasan(self, running):
        st = running.store
        count_all(st, {"8991001": [1], "8991002": [2], "12": [3]})
        s = st.finalize()
        d = main.session_to_fb(s)
        assert d["status"] == "final" and d["summary"]["n"] == 3 and d["items"]["8991001"]["diff"] == -23
        assert main.session_from_fb(d, s["id"])["status"] == "final"

    def test_produk_dan_data_rusak(self):
        assert main.product_from_fb("A%2EB", {"desc": "x", "oh": 2})["plu"] == "A.B"
        assert main.product_from_fb("k", {"desc": "", "oh": 2}) is None and main.product_from_fb("k", "x") is None
        assert main.session_from_fb(None, "x") is None
        assert main.session_from_fb({"items": {"a": {"oh": "bukan angka"}, "b": 5}}, "S")["items"] == []

    @pytest.mark.parametrize("raw,out", [("x.firebaseio.com", "https://x.firebaseio.com"), (" https://x.firebaseio.com/ ", "https://x.firebaseio.com"),
                                         ("https://x.firebaseio.com/stockopname.json?a=1", "https://x.firebaseio.com"), ("http://127.0.0.1:9000", "http://127.0.0.1:9000")])
    def test_normalisasi_url(self, raw, out):
        assert main.normalize_db_url(raw) == out

    @pytest.mark.parametrize("raw", ["", "  ", "ftp://x", "https://"])
    def test_url_tidak_valid(self, raw):
        with pytest.raises(ValueError):
            main.normalize_db_url(raw)

    def test_path_root(self):
        assert main.clean_root("") == "stockopname" and main.clean_root("/toko/a/") == "toko/a"
        with pytest.raises(ValueError):
            main.clean_root("toko.a")


# ====================================================== 7. Firebase: HTTP sungguhan ke server palsu
class TestFirebaseHTTP:
    def test_ping_ok_dan_menyertakan_token(self, fake_db):
        assert fb(fake_db).ping()
        assert all(q.get("auth") == "rahasia" for _, _, q in fake_db.log) and fake_db.data["stockopname"]["_meta"]["app"] == "stock-opname"

    def test_token_salah_atau_kosong(self, fake_db):
        for kw in ({"auth": "salah"}, {"auth": ""}):
            with pytest.raises(main.FirebaseError, match="Akses ditolak"):
                fb(fake_db, **kw).ping()

    def test_url_salah_dan_server_mati(self, fake_db):
        with pytest.raises(main.FirebaseError, match="Tidak dapat terhubung"):
            main.Firebase("http://127.0.0.1:1", timeout=2).ping()               # port tertutup
        fake_db.fail = 500
        with pytest.raises(main.FirebaseError, match="Server Firebase bermasalah"):
            fb(fake_db).ping()
        fake_db.fail = 404
        with pytest.raises(main.FirebaseError, match="tidak ditemukan"):
            fb(fake_db).ping()
        fake_db.fail = 400
        with pytest.raises(main.FirebaseError, match="ditolak Firebase"):
            fb(fake_db).ping()

    def test_kirim_dan_ambil_produk_sampai_kunci_aneh(self, seeded, fake_db):
        main.sync_push_all(fb(fake_db), seeded.store)
        stored = fake_db.data["stockopname"]["products"]
        assert set(stored) == {"8991001", "8991002", "8991003", "12", "A%2EB%2F1"}      # kunci legal, tersimpan apa adanya
        other = main.Store(seeded.tmp / "hp-lain")
        res = main.sync_pull_all(fb(fake_db), other)
        assert res["products"] == 5 and other.products() == seeded.store.products()     # sama persis, termasuk "A.B/1"

    def test_sesi_berjalan_dan_final_lintas_perangkat(self, running, fake_db):
        st = running.store
        st.set_counts("8991001", [10, None, 3])
        main.sync_push_all(fb(fake_db), st)
        hp2 = main.Store(running.tmp / "hp2")
        r = main.sync_pull_all(fb(fake_db), hp2)
        assert r["session"] == st.session()["id"] and hp2.session() == st.session()
        count_all(hp2, {"8991002": [1], "12": [2]})
        hp2.set_counts("8991001", [24])
        final = hp2.finalize()
        main.sync_push_all(fb(fake_db), hp2)
        assert fake_db.data["stockopname"]["sessions"][final["id"]]["status"] == "final"
        assert main.sync_pull_all(fb(fake_db), st)["session"] == final["id"] and st.session()["status"] == "final"

    def test_tanpa_array_dan_dengan_print_silent(self, running, fake_db):
        main.sync_push_all(fb(fake_db), running.store)
        assert fake_db.saw_list is False                                                # hitungan kosong tak boleh jadi array
        assert all(q.get("print") == "silent" for m, _, q in fake_db.log if m == "PUT")

    def test_produk_kosong_tidak_menghapus_data_firebase(self, seeded, fake_db):
        main.sync_push_all(fb(fake_db), seeded.store)
        empty = main.Store(seeded.tmp / "kosong")
        main.sync_push_all(fb(fake_db), empty)
        assert len(fake_db.data["stockopname"]["products"]) == 5

    def test_satu_produk_dan_hapus(self, seeded, fake_db):
        c = fb(fake_db)
        c.put_product(seeded.store.products()["A.B/1"])
        assert list(fake_db.data["stockopname"]["products"]) == ["A%2EB%2F1"]
        c.delete_product("a.b/1")                                                       # huruf kecil dinormalkan
        assert "products" not in fake_db.data.get("stockopname", {})        # node kosong hilang, seperti Firebase asli

    def test_root_terpisah_per_toko(self, seeded, fake_db):
        main.sync_push_all(fb(fake_db, root="toko/a"), seeded.store)
        assert "products" in fake_db.data["toko"]["a"] and "stockopname" not in fake_db.data
        assert main.sync_pull_all(fb(fake_db, root="toko/b"), main.Store(seeded.tmp / "b"))["products"] == 0

    def test_unicode(self, env, fake_db):
        env.store.upsert_product("日本酒", "Sake Jepang é ñ", 2)
        main.sync_push_all(fb(fake_db), env.store)
        other = main.Store(env.tmp / "u")
        main.sync_pull_all(fb(fake_db), other)
        assert other.products()["日本酒"]["desc"] == "Sake Jepang é ñ"


# ====================================================== 8. sinkron otomatis
class TestAutoSync:
    def cfg(self, env, db, **kw):
        env.store.save_config(dict({"url": db.url, "root": "stockopname", "auth": db.secret, "auto": True}, **kw))

    def test_mati_secara_bawaan_dan_tanpa_url(self, env, fake_db):
        assert main.auto_sync(lambda f, p: f.put_product(p), {"plu": "A", "desc": "x", "oh": 1}) is False
        self.cfg(env, fake_db, auto=False)
        assert main.auto_sync(lambda f: None) is False and fake_db.log == []

    def test_menyimpan_produk_otomatis_terkirim(self, env, fake_db):
        self.cfg(env, fake_db)
        scr = screen(main.ProductsScreen)
        scr.ids.f_plu.text, scr.ids.f_desc.text, scr.ids.f_oh.text = "8991001", "Susu", "24"
        scr.save()
        assert fake_db.data["stockopname"]["products"]["8991001"]["oh"] == 24 and env.nav.sync_status.startswith("Firebase: tersinkron")
        scr.pick("8991001"); scr.ask_delete(); env.pops[-1].btn["Ya, hapus"]()
        assert "products" not in fake_db.data.get("stockopname", {})        # node kosong hilang, seperti Firebase asli

    def test_gagal_hanya_mencatat_status_dan_tetap_lokal(self, env, fake_db):
        self.cfg(env, fake_db, auth="salah")
        scr = screen(main.ProductsScreen)
        scr.ids.f_plu.text, scr.ids.f_desc.text, scr.ids.f_oh.text = "A", "x", "1"
        scr.save()
        assert "A" in env.store.products() and "gagal" in env.nav.sync_status and "Akses ditolak" in env.nav.sync_status

    def test_konfigurasi_rusak_dilaporkan(self, env):
        env.store.save_config({"url": "ftp://x", "auto": True})
        assert main.auto_sync(lambda f: None) is False and "tidak valid" in env.nav.sync_status

    def test_run_async_asli_memanggil_balik_di_thread_kivy(self):
        CLOCK.events.clear()
        got = []
        ORIG_RUN_ASYNC(lambda: 42, lambda r, e: got.append((r, e)))
        for _ in range(100):
            if CLOCK.events:
                break
            time.sleep(0.02)
        assert got == []                                                               # belum: menunggu jadwal thread Kivy
        CLOCK.events[-1].fn(0)
        assert got == [(42, None)]
        CLOCK.events.clear()
        ORIG_RUN_ASYNC(lambda: 1 / 0, lambda r, e: got.append((r, type(e))))
        for _ in range(100):
            if CLOCK.events:
                break
            time.sleep(0.02)
        CLOCK.events[-1].fn(0)
        assert got[-1] == (None, ZeroDivisionError)


# ====================================================== 9. gambar laporan PNG
class TestReport:
    def sess(self, n=3, final=True):
        items = [("P%03d" % i, "Produk nomor %d" % i, 10, [10 + (i % 3) - 1, None, None, None, None]) for i in range(n)]
        return mk_session(items, "final" if final else "open")

    def test_png_sah_dan_ukuran(self):
        pages = main.render_report(self.sess(3))
        assert len(pages) == 1
        w, h, rows = decode_png(pages[0])
        L = lay()
        assert w == sum(x for _, x in main.REPORT_COLS) + 2 * L.pad
        assert h == L.head_h + L.sum_h + L.th_h + 3 * L.row_h + L.tot_h + (L.ch + 30)

    @pytest.mark.parametrize("n,per,pages", [(1, 20, 1), (20, 20, 1), (21, 20, 2), (45, 20, 3), (7, 3, 3), (1, 1, 1)])
    def test_pagination(self, n, per, pages):
        out = main.render_report(self.sess(n), rows_per_page=per)
        assert len(out) == pages
        for d in out:
            decode_png(d)

    def test_warna_header_dan_baris_menurut_selisih(self):
        s = mk_session([("A", "kurang", 10, [8, None, None, None, None]), ("B", "sesuai", 10, [10, None, None, None, None]),
                        ("C", "lebih", 10, [12, None, None, None, None])])
        w, h, rows = decode_png(main.render_report(s)[0])
        L = lay()
        assert px(rows, 2, 2) == main.C_NAVY and px(rows, w - 2, 2) == main.C_NAVY                 # pita judul
        y0 = L.head_h + L.sum_h + L.th_h
        probe_x = L.pad + L.cols["desc"] - 4
        assert px(rows, probe_x, y0 + 35) == main.C_BAD_BG                                          # kurang = merah muda
        assert px(rows, probe_x, y0 + L.row_h + 35) == main.C_OK_BG                                 # sesuai = hijau muda
        assert px(rows, probe_x, y0 + 2 * L.row_h + 35) == main.C_WARN_BG                           # lebih = kuning muda

    def test_teks_tergambar_dan_sel_kosong_bersih(self):
        s = mk_session([("A", "Barang", 10, [8, None, None, None, None])])
        w, h, rows = decode_png(main.render_report(s)[0])
        L = lay()
        y0 = L.head_h + L.sum_h + L.th_h

        def inked(x0, x1, y0_, y1):
            return any(px(rows, x, y) != px(rows, x0, y0_) for y in range(y0_, y1) for x in range(x0, x1))
        assert inked(L.pad, L.pad + 400, 10, 50)                                                    # judul ada
        assert inked(L.xs[0] + 8, L.xs[0] + 150, y0 + 5, y0 + L.row_h - 5)                          # PLU/deskripsi ada
        assert inked(L.xs[2] + 5, L.xs[2] + L.cols["c1"] - 5, y0 + 5, y0 + L.row_h - 5)             # kolom 1 terisi (8)
        assert not inked(L.xs[3] + 5, L.xs[3] + L.cols["c2"] - 5, y0 + 5, y0 + L.row_h - 5)         # kolom 2 kosong -> bersih
        assert inked(L.xs[7] + 5, L.xs[7] + L.cols["tot"] - 5, y0 + 5, y0 + L.row_h - 5)            # total fisik
        assert inked(L.xs[8] + 5, L.xs[8] + L.cols["dif"] - 5, y0 + 5, y0 + L.row_h - 5)            # selisih

    def test_baris_total_tergambar_dengan_warna_selisih(self):
        s = mk_session([("A", "x", 10, [8, None, None, None, None]), ("B", "y", 10, [7, None, None, None, None])])   # total selisih -5
        w, h, rows = decode_png(main.render_report(s)[0])
        L = lay()
        y = L.head_h + L.sum_h + L.th_h + 2 * L.row_h
        band = lambda x0, x1: {px(rows, x, yy) for yy in range(y + 3, y + L.tot_h - 3) for x in range(x0, x1)}
        assert px(rows, L.pad + 2, y + 2) == main.C_HEAD                                           # pita total
        assert len(band(L.xs[0] + 8, L.xs[0] + 200)) > 1                                           # tulisan "TOTAL (2 produk)"
        assert main.C_BAD in band(L.xs[8] + 5, L.xs[8] + L.cols["dif"] - 5)                        # selisih total merah
        assert len(band(L.xs[1] + 5, L.xs[1] + L.cols["oh"] - 5)) > 1 and len(band(L.xs[7] + 5, L.xs[7] + L.cols["tot"] - 5)) > 1

    def test_sementara_vs_final_berbeda(self):
        assert main.render_report(self.sess(2, True)) != main.render_report(self.sess(2, False))

    def test_karakter_non_ascii_dan_kepanjangan(self):
        a = mk_session([("A", "Kopi é ñ 日本", 1, [1, None, None, None, None])])
        b = mk_session([("A", "Kopi ? ? ??", 1, [1, None, None, None, None])])
        assert main.render_report(a) == main.render_report(b)                                       # tak didukung -> '?'
        assert main.fit("x" * 50, 10) == "x" * 8 + ".." and main.fit("a\nb\tc", 9) == "a b c" and main.fit_num("123456789", 5) == "1234~"
        long = mk_session([("P" * 40, "D" * 120, 123456789.5, [987654321.5, None, None, None, None])])
        decode_png(main.render_report(long)[0])                                                     # tidak error / tidak keluar kanvas

    def test_halaman_terakhir_punya_total(self):
        out = main.render_report(self.sess(25), rows_per_page=20)
        h1, h2 = decode_png(out[0])[1], decode_png(out[1])[1]
        L = lay()
        assert h1 == L.head_h + L.sum_h + L.th_h + 20 * L.row_h + (L.ch + 30)                       # hal.1: ringkasan, tanpa total
        assert h2 == L.head_h + L.th_h + 5 * L.row_h + L.tot_h + (L.ch + 30)                        # hal.2: tanpa ringkasan, ada total

    def test_export_menulis_berkas_dan_membersihkan_yang_lama(self, env):
        s = self.sess(25)
        paths = main.export_report(env.store, s, rows_per_page=10)
        assert [p.name for p in paths] == ["SO-TEST_01.png", "SO-TEST_02.png", "SO-TEST_03.png"] and all(decode_png(p.read_bytes()) for p in paths)
        paths2 = main.export_report(env.store, s, rows_per_page=30)
        assert len(paths2) == 1 and sorted(p.name for p in env.store.export_dir.iterdir()) == ["SO-TEST_01.png"]

    def test_sesi_kosong_tidak_crash(self):
        decode_png(main.render_report(mk_session([]))[0])


# ====================================================== 10. kirim ke WhatsApp
class TestShare:
    def fake_modules(self, raise_on_app=False, copy_result="uri"):
        calls = SimpleNamespace(copied=[], shared=[])

        class SharedStorage:
            def copy_to_shared(self, p):
                calls.copied.append(p)
                return None if copy_result is None else "content://media/%d" % len(calls.copied)

        class ShareSheet:
            def share_file(self, f, app=None):
                if raise_on_app and app:
                    raise RuntimeError("ActivityNotFound")
                calls.shared.append(("file", f, app))

            def share_file_list(self, fl, app=None):
                if raise_on_app and app:
                    raise RuntimeError("ActivityNotFound")
                calls.shared.append(("list", list(fl), app))
        m = types.ModuleType("androidstorage4kivy")
        m.SharedStorage, m.ShareSheet = SharedStorage, ShareSheet
        sys.modules["androidstorage4kivy"] = m
        return calls

    def test_satu_gambar_langsung_ke_whatsapp(self):
        calls = self.fake_modules()
        try:
            sheet = main.android_share(["/p/a.png"])
        finally:
            del sys.modules["androidstorage4kivy"]
        assert calls.copied == ["/p/a.png"] and calls.shared == [("file", "content://media/1", "com.whatsapp")] and sheet is not None

    def test_banyak_halaman_satu_kali_kirim(self):
        calls = self.fake_modules()
        try:
            main.android_share(["/p/1.png", "/p/2.png", "/p/3.png"], "com.whatsapp.w4b")
        finally:
            del sys.modules["androidstorage4kivy"]
        assert calls.shared == [("list", ["content://media/1", "content://media/2", "content://media/3"], "com.whatsapp.w4b")]

    def test_whatsapp_tak_ada_beralih_ke_pilihan_aplikasi(self):
        calls = self.fake_modules(raise_on_app=True)
        try:
            main.android_share(["/p/1.png", "/p/2.png"])
        finally:
            del sys.modules["androidstorage4kivy"]
        assert calls.shared == [("list", ["content://media/1", "content://media/2"], None)]

    def test_gagal_menyalin_dilaporkan(self):
        self.fake_modules(copy_result=None)
        try:
            with pytest.raises(RuntimeError, match="menyalin"):
                main.android_share(["/p/1.png"])
        finally:
            del sys.modules["androidstorage4kivy"]

    def test_desktop_hanya_melaporkan_lokasi(self):
        out = []
        main.share_images([Path("/x/a.png"), Path("/x/b.png")], on_done=lambda ok, m: out.append((ok, m)))
        assert out == [(False, "Gambar disimpan di:\n/x/a.png\n/x/b.png")]

    def test_alur_android_sdk_baru_tanpa_izin(self, env, monkeypatch):
        calls = self.fake_modules()
        jn = types.ModuleType("jnius"); jn.autoclass = lambda n: SimpleNamespace(SDK_INT=34)
        sys.modules["jnius"] = jn
        monkeypatch.setattr(main, "platform", "android")
        out = []
        try:
            main.share_images([Path("/x/a.png")], on_done=lambda ok, m: out.append((ok, m)))
        finally:
            del sys.modules["androidstorage4kivy"], sys.modules["jnius"]
        assert out == [(True, "WhatsApp dibuka (1 gambar).")] and calls.shared and env.nav._sheet is not None

    def test_android_9_ke_bawah_minta_izin_dulu(self, env, monkeypatch):
        calls = self.fake_modules()
        jn = types.ModuleType("jnius"); jn.autoclass = lambda n: SimpleNamespace(SDK_INT=28)
        asked = []
        pm = types.ModuleType("android.permissions")
        pm.Permission = SimpleNamespace(WRITE_EXTERNAL_STORAGE="WES")
        pm.request_permissions = lambda perms, cb: asked.append((perms, cb))
        for n, m in (("jnius", jn), ("android", types.ModuleType("android")), ("android.permissions", pm)):
            sys.modules[n] = m
        monkeypatch.setattr(main, "platform", "android")
        out = []
        try:
            main.share_images([Path("/x/a.png")], on_done=lambda ok, m: out.append((ok, m)))
            assert asked[0][0] == ["WES"] and calls.shared == []                       # menunggu jawaban izin
            asked[0][1](["WES"], [True])
            assert calls.shared and out[-1][0] is True
            out.clear()
            main.share_images([Path("/x/a.png")], on_done=lambda ok, m: out.append((ok, m)))
            asked[1][1](["WES"], [False])                                              # izin ditolak
            assert out[-1][0] is False and "Izin penyimpanan ditolak" in out[-1][1] and "/x/a.png" in out[-1][1]
        finally:
            for n in ("androidstorage4kivy", "jnius", "android", "android.permissions"):
                sys.modules.pop(n, None)

    def test_kegagalan_pemilih_aplikasi_dilaporkan_bersama_lokasi_gambar(self, env, monkeypatch):
        monkeypatch.setattr(main, "platform", "android")
        monkeypatch.setattr(main, "ensure_write_permission", lambda then, denied: then())
        monkeypatch.setattr(main, "android_share", lambda p, pkg: (_ for _ in ()).throw(RuntimeError("boom")))
        out = []
        main.share_images([Path("/x/a.png")], on_done=lambda ok, m: out.append((ok, m)))
        assert out[0][0] is False and "boom" in out[0][1] and "/x/a.png" in out[0][1]


# ====================================================== 11. layar & alur pengguna
class TestScreens:
    def test_beranda_ringkasan(self, env):
        h = screen(main.HomeScreen)
        h.refresh()
        assert "Produk terdaftar: [b]0[/b]" in h.ids.status.text and "Belum ada item" in h.ids.status.text and "tidak dipakai" in h.ids.status.text
        seed(env.store); env.store.apply_setup(["12"])
        env.nav.sync_status = "Firebase: gagal [x]"
        h.refresh()
        assert "[b]5[/b]" in h.ids.status.text and "0/1 dihitung (berjalan)" in h.ids.status.text and valid_markup(h.ids.status.text)

    def test_input_sku(self, env):
        p = screen(main.ProductsScreen)
        p.ids.f_plu.text, p.ids.f_desc.text, p.ids.f_oh.text = "8991001", "Susu [UHT] & Co", "24"
        p.save()
        assert "Tersimpan" in p.ids.msg.text and p.ids.f_plu.text == "" and len(p.ids.rv.data) == 1
        assert valid_markup(p.ids.rv.data[0]["text"]) and "OH: 24" in p.ids.rv.data[0]["text"] and p.ids.info.text == "1 produk"
        p.ids.f_plu.text, p.ids.f_desc.text, p.ids.f_oh.text = "8991001", "Dobel", "1"      # PLU ganda tanpa memilih
        p.save()
        assert "sudah ada" in p.ids.msg.text and env.store.products()["8991001"]["oh"] == 24
        p.pick("8991001")
        assert p.ids.f_plu.readonly and p.ids.b_save.text == "Perbarui" and not p.ids.b_del.disabled and p.ids.f_oh.text == "24"
        p.ids.f_oh.text = "30"; p.save()
        assert env.store.products()["8991001"]["oh"] == 30 and "Diperbarui" in p.ids.msg.text and not p.ids.f_plu.readonly and p.ids.b_save.text == "Simpan"
        p.ids.f_plu.text, p.ids.f_desc.text, p.ids.f_oh.text = "X", "y", "abc"
        p.save()
        assert "angka" in p.ids.msg.text and valid_markup(p.ids.msg.text) and "X" not in env.store.products()

    def test_input_sku_cari_dan_hapus(self, seeded):
        p = screen(main.ProductsScreen)
        p.refresh()
        assert len(p.ids.rv.data) == 5
        p.ids.q.text = "teh"; p.refresh()
        assert [r["plu"] for r in p.ids.rv.data] == ["8991002"] and "tampil 1" in p.ids.info.text
        p.ask_delete(); assert not seeded.pops                                           # belum memilih -> tidak ada dialog
        p.pick("8991002"); p.ask_delete()
        assert seeded.pops[-1].title == "Hapus produk"
        seeded.pops[-1].btn["Ya, hapus"]()
        assert "8991002" not in seeded.store.products() and p.editing is None

    def test_setting_item_so_memilih_dan_menyimpan(self, seeded):
        s = screen(main.SetupScreen)
        s.load()
        assert s.sel == set() and len(s.ids.rv.data) == 5 and "Dipilih [b]0[/b] dari 5" in s.ids.info.text
        s.ask_save()
        assert seeded.pops[-1].title == "Belum ada item"
        s.toggle("8991001"); s.toggle("12"); s.toggle("8991001"); s.toggle("8991001")
        assert s.sel == {"12", "8991001"} and "DIPILIH" in [r for r in s.ids.rv.data if r["plu"] == "12"][0]["text"] and "Dipilih [b]2[/b]" in s.ids.info.text
        s.ask_save()
        assert seeded.pops[-1].title == "Konfirmasi setup" and "[b]2[/b]" in seeded.pops[-1].msg and seeded.store.session() is None
        seeded.pops[-1].btn["Ya, simpan"]()
        assert [i["plu"] for i in seeded.store.session()["items"]] == ["12", "8991001"] and seeded.pops[-1].title == "Setup tersimpan"
        seeded.pops[-1].btn["Buka Stock Opname"]()
        assert seeded.nav.root.current == "so"

    def test_setting_pilih_semua_kosongkan_dengan_pencarian(self, seeded):
        s = screen(main.SetupScreen)
        s.load()
        s.ids.q.text = "8991"; s.select_all()
        assert s.sel == {"8991001", "8991002", "8991003"}
        s.ids.q.text = "8991002"; s.clear_all()
        assert s.sel == {"8991001", "8991003"}
        s.ids.q.text = ""; s.select_all()
        assert len(s.sel) == 5 and "[b]5[/b]" in s.ids.info.text
        s.ids.q.text = ""; s.clear_all()
        assert s.sel == set()

    def test_setup_ulang_memperingatkan_dampak(self, running):
        st = running.store
        st.set_counts("8991001", [5]); st.set_counts("8991002", [6])
        s = screen(main.SetupScreen)
        s.load()
        assert s.sel == {"8991001", "8991002", "12"}                                  # terisi dari sesi berjalan
        s.toggle("8991002"); s.toggle("8991003")                                      # keluarkan yang sudah dihitung, tambah baru
        s.ask_save()
        msg = running.pops[-1].msg
        assert "1 item sudah punya hasil hitung dan dipertahankan" in msg and "1 item yang sudah dihitung dikeluarkan" in msg and valid_markup(msg)

    def test_setup_setelah_final_memperingatkan_sesi_baru(self, running):
        count_all(running.store, {"8991001": [1], "8991002": [2], "12": [3]})
        running.store.finalize()
        s = screen(main.SetupScreen)
        s.load(); s.ask_save()
        assert "FINAL" in running.pops[-1].msg and "sesi BARU" in running.pops[-1].msg

    def test_tabel_so_baris_dan_format(self, running):
        st = running.store
        st.set_counts("8991001", [10, 5, None, 7, None])
        rows = main.so_rows(st.session())
        assert [r["plu"] for r in rows] == ["12", "8991001", "8991002"]
        r = rows[1]
        assert (r["oh"], r["c1"], r["c2"], r["c3"], r["c4"], r["c5"], r["total"], r["diff"]) == ("24", "10", "5", "", "7", "", "22", "-2")
        assert r["dcolor"] == list(main.BAD) and rows[0]["total"] == "" and rows[0]["diff"] == "" and rows[0]["bg"] == [1, 1, 1, 1]
        assert "Susu UHT Coklat 200ml" in r["title"] and all(valid_markup(x["title"]) for x in rows)
        assert [x["plu"] for x in main.so_rows(st.session(), "teh")] == ["8991002"]

    def test_so_screen_progres_dan_tombol(self, running):
        so = screen(main.SOScreen)
        so.reload()
        assert "Dihitung [b]0/3[/b]" in so.ids.progress.text and so.ids.b_fin.disabled is False and so.ids.b_wa.disabled and so.ids.b_rev.disabled
        assert len(so.ids.rv.data) == 3

    def test_so_tanpa_sesi(self, env):
        so = screen(main.SOScreen)
        so.reload()
        assert "Belum ada item" in so.ids.progress.text and so.ids.rv.data == [] and so.ids.b_fin.disabled

    def test_editor_hitungan_live_simpan_dan_berikutnya(self, running):
        so = screen(main.SOScreen)
        so.reload()
        so.edit("8991001", 2)
        ed = so.editor
        assert "Isi minimal satu kolom" in ed.info.text and len(ed.inputs) == 5
        for ti, v in zip(ed.inputs, ["10", "5,5", "", "7", ""]):
            ti.text = v
        ed.refresh()
        assert "Total Fisik: [b]22.5[/b]" in ed.info.text and "-1.5" in ed.info.text and valid_markup(ed.info.text)     # 22.5 - 24
        ed.inputs[2].text = "abc"
        ed.refresh()
        assert "Angka tidak valid" in ed.info.text and ed.save() is False and running.store.item("8991001")["counts"] == [None] * 5
        ed.inputs[2].text = ""
        ed.inputs[4].text = "-1"
        assert ed.save() is False and "negatif" in ed.info.text
        ed.inputs[4].text = ""
        assert ed.save(advance=True) is True
        assert running.store.item("8991001")["counts"] == [10, 5.5, None, 7, None]
        assert so.ids.rv.data[1]["total"] == "22.5" and so.ids.rv.data[1]["diff"] == "-1.5"
        assert so.editor is not ed and so.editor.plu == "8991002"                      # lanjut ke produk berikutnya

    def test_editor_produk_terakhir_tidak_membuka_lagi(self, running):
        so = screen(main.SOScreen)
        so.reload(); so.edit("8991002", 1)
        so.editor.inputs[0].text = "30"
        ed = so.editor
        so.editor.save(advance=True)
        assert so.editor is ed and so.next_plu("8991002") is None and so.next_plu("12") == "8991001"

    def test_edit_diblokir_setelah_final(self, running):
        st = running.store
        count_all(st, {"8991001": [1], "8991002": [2], "12": [3]})
        st.finalize()
        so = screen(main.SOScreen)
        so.reload()
        assert so.ids.b_fin.disabled and not so.ids.b_wa.disabled and not so.ids.b_rev.disabled and "FINAL" in so.ids.progress.text
        so.edit("12", 1)
        assert running.pops[-1].title == "Sesi sudah final" and not hasattr(so, "editor")

    def test_simpan_konfirmasi_belum_lengkap_ditolak(self, running):
        so = screen(main.SOScreen)
        running.store.set_counts("8991001", [1])
        so.finish()
        assert running.pops[-1].title == "Belum lengkap" and "[b]2[/b]" in running.pops[-1].msg and "12, 8991002" in running.pops[-1].msg
        assert running.store.session()["status"] == "open"

    def test_alur_penuh_simpan_konfirmasi_kirim_wa(self, running, monkeypatch):
        st = running.store
        count_all(st, {"8991001": [10, 12], "8991002": [30, 6], "12": [7, 1]})        # 22 vs 24 (-2) | 36 vs 36 (0) | 8 vs 7.5 (+0.5)
        so = screen(main.SOScreen)
        sent = []
        monkeypatch.setattr(main, "share_images", lambda paths, pkg, cb: sent.append((list(paths), pkg)))
        so.finish()
        conf = running.pops[-1]
        assert conf.title == "Konfirmasi Stock Opname" and "Sesuai: [b]1[/b]" in conf.msg and "Kurang: [b]1[/b]" in conf.msg and "Lebih: [b]1[/b]" in conf.msg
        assert "-1.5" in conf.msg and valid_markup(conf.msg) and st.session()["status"] == "open" and sent == []       # belum final sebelum konfirmasi
        assert conf.btn["Batal"] is None                                                # batal = tutup dialog, tanpa aksi
        assert st.session()["status"] == "open" and sent == []
        conf.btn["Ya, simpan & kirim"]()
        assert st.session()["status"] == "final" and st.session()["summary"]["short"] == 1
        assert len(sent) == 1 and sent[0][1] == "com.whatsapp" and all(p.suffix == ".png" and p.exists() for p in sent[0][0])
        decode_png(sent[0][0][0].read_bytes())
        assert so.ids.b_fin.disabled and not so.ids.b_wa.disabled
        so.share()                                                                     # kirim ulang dari tombol Kirim WA
        assert len(sent) == 2

    def test_hasil_pengiriman_gagal_ditampilkan(self, running):
        so = screen(main.SOScreen)
        so._shared(True, "ok")
        assert running.pops == []
        so._shared(False, "Gambar disimpan di:\n/x/[a].png")
        assert running.pops[-1].title == "Laporan PNG" and valid_markup(running.pops[-1].msg)

    def test_revisi(self, running):
        st = running.store
        count_all(st, {"8991001": [1], "8991002": [2], "12": [3]})
        st.finalize()
        so = screen(main.SOScreen)
        so.ask_reopen()
        running.pops[-1].btn["Ya, buka"]()
        assert st.session()["status"] == "open" and not so.ids.b_fin.disabled and so.ids.b_wa.disabled

    def test_layar_firebase(self, running, fake_db):
        fs = screen(main.FirebaseScreen)
        fs.load()
        assert fs.ids.url.text == "" and fs.ids.rootpath.text == "stockopname" and fs.ids.auto.active is False
        fs.ids.url.text = "ftp://salah"
        assert fs.save() is False and "tidak valid" in fs.ids.msg.text
        fs.ids.url.text = fake_db.url; fs.ids.auth.text = "salah"
        fs.test()
        assert "Gagal" in fs.ids.msg.text and "Akses ditolak" in fs.ids.msg.text and valid_markup(fs.ids.msg.text)
        fs.ids.auth.text = "rahasia"; fs.ids.auto.active = True
        fs.test()
        assert "Koneksi berhasil" in fs.ids.msg.text and running.store.config()["auto"] is True and running.store.config()["url"] == fake_db.url
        fs.push()
        assert "Terkirim: 5 produk" in fs.ids.msg.text and "stockopname" in fake_db.data
        running.store.delete_product("12")
        fs.ask_pull(); assert "menggantikan" in running.pops[-1].msg
        running.pops[-1].btn["Ya, ambil"]()
        assert "Diambil: 5 produk" in fs.ids.msg.text and "12" in running.store.products()
        fs.ids.url.text = ""
        assert fs.save() and "lokal saja" in fs.ids.msg.text
        fs.test()
        assert "belum diisi" in fs.ids.msg.text

    def test_tanpa_firebase_semua_fitur_tetap_jalan(self, env):
        """Inti permintaan: berjalan TANPA database. Tidak ada permintaan jaringan sama sekali."""
        orig = main.urllib.request.urlopen
        main.urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(AssertionError("jaringan dipakai!"))
        try:
            p = screen(main.ProductsScreen)
            for plu, d, oh in (("1", "A", "5"), ("2", "B", "3")):
                p.ids.f_plu.text, p.ids.f_desc.text, p.ids.f_oh.text = plu, d, oh
                p.save()
            s = screen(main.SetupScreen); s.load(); s.select_all(); s.ask_save(); env.pops[-1].btn["Ya, simpan"]()
            count_all(env.store, {"1": [5], "2": [2]})
            so = screen(main.SOScreen); so.reload(); so.finish(); env.pops[-1].btn["Ya, simpan & kirim"]()
        finally:
            main.urllib.request.urlopen = orig
        assert env.store.session()["status"] == "final"


# ====================================================== 12. aplikasi
class TestApp:
    def test_tombol_kembali_dan_jeda(self, env):
        app = main.StockOpnameApp()
        app.root = SimpleNamespace(current="so")
        assert app._on_key(None, 27) is True and app.root.current == "home"
        assert app._on_key(None, 27) is False                                          # di beranda: keluar
        assert app._on_key(None, 97) is False
        app.root.current = "setup"
        assert app.on_pause() is True

    def test_popup_terbuka_ditutup_dulu(self, env, monkeypatch):
        monkeypatch.setattr(main, "popup", ORIG_POPUP)
        app = main.StockOpnameApp()
        app.root = SimpleNamespace(current="so")
        main.popup("T", "pesan", [("OK", None, True)])
        assert len(main.OPEN_POPUPS) == 1
        assert app._on_key(None, 27) is True and app.root.current == "so" and main.OPEN_POPUPS == []
        assert app._on_key(None, 27) is True and app.root.current == "home"

    def test_delegasi_ke_layar(self, env):
        app = main.StockOpnameApp()
        calls = []
        app.root = SimpleNamespace(current="home", get_screen=lambda n: SimpleNamespace(
            pick=lambda p: calls.append(("pick", n, p)), toggle=lambda p: calls.append(("toggle", n, p)),
            edit=lambda p, c: calls.append(("edit", n, p, c))))
        app.pick_product("A"); app.toggle_setup("B"); app.edit_counts("C", 3); app.go("so")
        assert calls == [("pick", "products", "A"), ("toggle", "setup", "B"), ("edit", "so", "C", 3)] and app.root.current == "so"

    def test_init_storage_di_user_data_dir(self):
        assert 'init_storage(Path(self.user_data_dir) / "data")' in SOURCE


ORIG_POPUP = main.popup


# ====================================================== 13. pengemasan (spec, workflow, README)
def spec():
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(HERE / "buildozer.spec", encoding="utf-8")
    return cp["app"]


class TestPackaging:
    def test_buildozer_spec(self):
        a = spec()
        reqs = {r.strip().split("==")[0] for r in a["requirements"].split(",")}
        assert {"python3", "kivy", "openssl", "certifi", "androidstorage4kivy", "pyjnius", "android"} <= reqs
        assert not ({"pandas", "numpy", "pillow", "requests", "firebase-admin", "pyrebase"} & reqs)   # tanpa paket C / SDK berat
        assert re.fullmatch(r"[a-z][a-z0-9]*", a["package.name"]) and (HERE / "main.py").exists() and (HERE / "fontdata.py").exists()
        perms = [x.strip() for x in a["android.permissions"].split(",")]
        assert "INTERNET" in perms and "WRITE_EXTERNAL_STORAGE" in perms and not [p for p in perms if "MANAGE_EXTERNAL" in p or "READ_" in p]
        assert a["android.accept_sdk_license"].lower() == "true" and a["android.release_artifact"] == "apk"
        assert "test_*.py" in a["source.exclude_patterns"] and "py" in a["source.include_exts"]
        # alat build dikunci: p4a 2026 rusak (issue kivy/python-for-android #3342) - sudah terbukti di lingkungan pengguna
        assert a["p4a.branch"] == "v2024.01.21" and a["android.ndk"] == "25b" and a["android.api"] == "33"
        assert "kivy==2.3.0" in a["requirements"] and a["android.archs"] == "arm64-v8a"

    def test_semua_impor_pihak_ketiga_ada_di_requirements(self):
        names = set()
        for n in ast.walk(ast.parse(SOURCE)):
            if isinstance(n, ast.Import):
                names |= {x.name.split(".")[0] for x in n.names}
            if isinstance(n, ast.ImportFrom) and n.level == 0:
                names.add(n.module.split(".")[0])
        local = {p.stem for p in HERE.glob("*.py")}
        alias = {"jnius": "pyjnius"}
        third = {alias.get(n, n) for n in names if n not in sys.stdlib_module_names and n not in local}
        reqs = {r.strip().split("==")[0] for r in spec()["requirements"].split(",")}
        assert third and third <= reqs, third - reqs

    def test_workflow_github_actions(self):
        try:
            import yaml
        except ImportError:
            return
        path = HERE / ".github" / "workflows" / "build-apk.yml"
        text = path.read_text(encoding="utf-8")
        wf = yaml.safe_load(text)
        on = wf.get("on", wf.get(True))
        assert "v*" in on["push"]["tags"] and "workflow_dispatch" in on and wf["permissions"]["contents"] == "write"
        assert set(wf["jobs"]) == {"test", "build"} and wf["jobs"]["build"]["needs"] == "test"
        steps = wf["jobs"]["build"]["steps"] + wf["jobs"]["test"]["steps"]
        uses = [x["uses"] for x in steps if "uses" in x]
        assert all("@" in u for u in uses)
        for need in ("actions/checkout", "actions/setup-python", "actions/setup-java", "actions/cache/restore", "actions/cache/save",
                     "actions/upload-artifact", "softprops/action-gh-release"):
            assert any(u.startswith(need) for u in uses), need
        assert all(isinstance(x["with"]["python-version"], str) for x in steps if x.get("uses", "").startswith("actions/setup-python"))
        for token in ("buildozer -v android debug", "buildozer -v android release", "P4A_RELEASE_KEYSTORE", "libffi-dev", "libtinfo6",
                      "libltdl-dev", "pytest -v test_main.py", "tee -a build.log", "GITHUB_STEP_SUMMARY", "prerelease", "Command failed"):
            assert token in text, token
        by = {x.get("name", ""): x for x in wf["jobs"]["build"]["steps"]}
        assert by["Ringkasan penyebab error (hanya bila gagal)"]["if"] == "failure()"
        save = next(x for x in wf["jobs"]["build"]["steps"] if x.get("uses", "").startswith("actions/cache/save"))
        rest = next(x for x in wf["jobs"]["build"]["steps"] if x.get("uses", "").startswith("actions/cache/restore"))
        assert save["if"] == "always()" and "p4a2024" in save["with"]["key"]
        assert all("p4a2024" in k for k in [rest["with"]["key"]] + rest["with"]["restore-keys"].strip().splitlines())

    def test_readme(self):
        r = (HERE / "README.md").read_text(encoding="utf-8")
        for token in ("Firebase", "WhatsApp", "Input SKU", "Setting Item Stock Opname", "Run workflow", "rules", "INTERNET"):
            assert token in r, token


# ====================================================== 14. skenario utuh & kinerja
class TestEndToEnd:
    def test_dari_input_sku_sampai_png_dan_firebase(self, env, fake_db):
        st = env.store
        st.save_config({"url": fake_db.url, "root": "toko1", "auth": "rahasia", "auto": True})
        prod = screen(main.ProductsScreen)
        for plu, d, oh in PRODUCTS:                                                    # Input SKU -> otomatis ke Firebase
            prod.ids.f_plu.text, prod.ids.f_desc.text, prod.ids.f_oh.text = plu, d, str(oh)
            prod.save()
        so_scr = screen(main.SetupScreen); so_scr.load(); so_scr.select_all(); so_scr.ask_save(); env.pops[-1].btn["Ya, simpan"]()
        assert len(st.session()["items"]) == 5
        hitung = {"12": [5, 2.5], "8991001": [24], "8991002": [10, 10, 10, 10, 10], "8991003": [60, 59], "A.B/1": [2]}
        sent = []
        scr = screen(main.SOScreen)
        main.share_images, orig = (lambda paths, pkg, cb: sent.append(paths)), main.share_images
        try:
            for plu, c in hitung.items():
                scr.reload(); scr.edit(plu, 1)
                for ti, v in zip(scr.editor.inputs, c):
                    ti.text = main.fmt_qty(v)
                assert scr.editor.save()
            scr.finish(); env.pops[-1].btn["Ya, simpan & kirim"]()
        finally:
            main.share_images = orig
        s = st.session()
        diffs = {i["plu"]: main.item_calc(i)[2] for i in s["items"]}
        assert diffs == {"12": 0.0, "8991001": 0.0, "8991002": 14.0, "8991003": -1.0, "A.B/1": -1.0}
        assert s["summary"]["ok"] == 2 and s["summary"]["short"] == 2 and s["summary"]["over"] == 1
        w, h, rows = decode_png(sent[0][0].read_bytes())
        assert w > 1000 and len(sent[0]) == 1
        remote = fake_db.data["toko1"]
        assert remote["sessions"][s["id"]]["status"] == "final" and remote["sessions"][s["id"]]["summary"]["diff_total"] == 12.0
        assert len(remote["products"]) == 5 and remote["meta"]["active_session"] == s["id"]


class TestPerformance:
    def test_5000_produk_cari_setup_dan_png_200_baris(self, env):
        st = env.store
        t0 = time.perf_counter()
        for i in range(5000):
            st.products()["%06d" % i] = {"plu": "%06d" % i, "desc": "Produk %d" % i, "oh": float(i % 50), "updated": ""}
        st._write("products.json", st.products())
        again = main.Store(st.base)
        found = again.product_list("Produk 49")
        t1 = time.perf_counter()
        s = again.apply_setup(["%06d" % i for i in range(200)])
        s = again.session()
        for it in s["items"]:
            it["counts"] = [it["oh"]] + [None] * 4
        s["status"] = "final"
        t2 = time.perf_counter()
        pages = main.render_report(s, rows_per_page=20)
        t3 = time.perf_counter()
        print("\n[kinerja] muat+cari 5000 produk: %.2fs | render 200 baris -> %d halaman: %.2fs | %d KB" % (t1 - t0, len(pages), t3 - t2, sum(map(len, pages)) // 1024))
        assert len(found) == 111 and len(pages) == 10 and t1 - t0 < 3 and t3 - t2 < 20
        for p in pages[:2]:
            decode_png(p)
