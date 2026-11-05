"""
Stock Opname (Kivy)
Berjalan TANPA database (data tersimpan lokal di perangkat) dan bisa disinkronkan ke
Firebase Realtime Database (REST, opsional).

Alur
  Beranda
    General       : Input SKU (data produk)  |  Setting Item Stock Opname (pilih item yang di-SO)
    Stock Opname  : tabel  PLU/Deskripsi | OH | 1 | 2 | 3 | 4 | 5 | Total Fisik | Selisih
                    Total Fisik = kolom 1+2+3+4+5,  Selisih = Total Fisik - OH
                    Semua produk sudah dihitung -> Simpan & Konfirmasi -> kirim PNG ke WhatsApp
    Firebase      : pengaturan sinkronisasi (opsional)

Instalasi : pip install kivy certifi
Pengujian : pip install pytest pyyaml && pytest -v test_main.py
Android   : lihat README.md (APK dibangun otomatis lewat GitHub Actions)
"""
import base64
import json
import os
import re
import socket
import ssl
import struct
import threading
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.uix.textinput import TextInput
from kivy.utils import escape_markup as esc
from kivy.utils import platform

SLOTS = 5                                   # kolom isi hitungan: 1..5
BASE = Path(__file__).resolve().parent / "data"
STORE = None                                # diisi init_storage()
OPEN_POPUPS = []                            # popup terbuka (tombol Kembali menutupnya dulu)

INK = (0.106, 0.141, 0.188, 1)
ACCENT = (0.231, 0.286, 0.875, 1)
DANGER = (0.78, 0.22, 0.27, 1)
SURFACE = (1, 1, 1, 1)
OKC = (0.106, 0.498, 0.231, 1)
BAD = (0.706, 0.137, 0.094, 1)
WARN = (0.706, 0.325, 0.035, 1)


# ============================================================ angka & teks
def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_session_id():
    return "SO-" + datetime.now().strftime("%Y%m%d-%H%M%S")


def natkey(s):
    """Urutan alami: PLU 2 sebelum PLU 10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def norm_plu(s):
    return re.sub(r"\s+", " ", (s or "").strip()).upper()


def clean1(s):
    return re.sub(r"\s+", " ", s or "").strip()


_QTY = re.compile(r"^[+-]?\d{1,12}(?:[.,]\d{1,3})?$")


def parse_qty(text, allow_negative=True):
    """'' -> None; '1,5' -> 1.5; selain angka biasa (mis. 'abc', '1e3', 'nan') -> ValueError."""
    s = (text or "").strip().replace(" ", "")
    if s == "":
        return None
    if not _QTY.match(s):
        raise ValueError("Angka tidak valid: %s" % (text or "").strip()[:20])
    v = round(float(s.replace(",", ".")), 3)
    if v < 0 and not allow_negative:
        raise ValueError("Tidak boleh negatif")
    return v


def fmt_qty(v):
    if v is None:
        return ""
    v = round(float(v), 3)
    return str(int(v)) if v == int(v) else ("%.3f" % v).rstrip("0").rstrip(".")


def fmt_diff(v):
    if v is None:
        return ""
    return ("+" if v > 0 else "") + fmt_qty(v)


def qty_filter(substring, _from_undo):
    """Kolom hitungan: hanya angka, titik, koma."""
    return "".join(c for c in substring if c in "0123456789.,")


def oh_filter(substring, _from_undo):
    """Kolom OH: boleh minus."""
    return "".join(c for c in substring if c in "0123456789.,-")


# ============================================================ perhitungan SO
def item_calc(it):
    """(sudah_dihitung, total_fisik, selisih). Total Fisik = kolom 1+2+3+4+5; Selisih = Total - OH."""
    vals = [c for c in it["counts"] if c is not None]
    if not vals:
        return False, None, None
    total = round(sum(vals), 3)
    return True, total, round(total - it["oh"], 3)


def summarize(session):
    n = len(session["items"])
    done = ok = short = over = 0
    oh_total = fisik_total = diff_total = 0.0
    for it in session["items"]:
        oh_total += it["oh"]
        d, total, diff = item_calc(it)
        if not d:
            continue
        done += 1
        fisik_total += total
        diff_total += diff
        if diff < 0:
            short += 1
        elif diff > 0:
            over += 1
        else:
            ok += 1
    return {"n": n, "done": done, "ok": ok, "short": short, "over": over,
            "oh_total": round(oh_total, 3), "fisik_total": round(fisik_total, 3),
            "diff_total": round(diff_total, 3)}


# ============================================================ penyimpanan lokal
def _atomic_write(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)  # atomik: berkas tidak rusak bila terhenti di tengah


DEFAULT_CONFIG = {"url": "", "root": "stockopname", "auth": "", "auto": False, "wa": "com.whatsapp"}


class Store:
    """Semua data tersimpan sebagai berkas JSON lokal. Tanpa server, tanpa database."""

    def __init__(self, base):
        self.base = Path(base)
        self.history_dir = self.base / "history"
        self.export_dir = self.base / "exports"
        for d in (self.base, self.history_dir, self.export_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._products = None

    def _read(self, name, default):
        try:
            return json.loads((self.base / name).read_text(encoding="utf-8"))
        except Exception:
            return default

    def _write(self, name, data):
        _atomic_write(self.base / name, data)

    # ---- produk (Input SKU)
    def products(self):
        if self._products is None:
            raw = self._read("products.json", {})
            ok = isinstance(raw, dict)
            self._products = {k: v for k, v in raw.items() if isinstance(v, dict) and v.get("desc")
                              and isinstance(v.get("oh"), (int, float))} if ok else {}
        return self._products

    def product_list(self, query=""):
        q = query.strip().lower()
        items = [p for p in self.products().values() if not q or q in p["plu"].lower() or q in p["desc"].lower()]
        return sorted(items, key=lambda p: natkey(p["plu"]))

    def upsert_product(self, plu, desc, oh, allow_update=True):
        plu, desc = norm_plu(plu), clean1(desc)
        if not plu:
            raise ValueError("PLU wajib diisi")
        if len(plu) > 40:
            raise ValueError("PLU maksimal 40 karakter")
        if not desc:
            raise ValueError("Deskripsi wajib diisi")
        if len(desc) > 120:
            raise ValueError("Deskripsi maksimal 120 karakter")
        if isinstance(oh, str):
            try:
                oh = parse_qty(oh)
            except ValueError:
                raise ValueError("OH harus berupa angka (contoh: 12 atau 2,5)")
        if oh is None:
            raise ValueError("OH (stok sistem) wajib diisi, isi 0 bila kosong")
        created = plu not in self.products()
        if not created and not allow_update:
            raise ValueError("PLU %s sudah ada. Ketuk produknya di daftar untuk mengubah." % plu)
        prod = {"plu": plu, "desc": desc, "oh": round(float(oh), 3), "updated": now_iso()}
        self.products()[plu] = prod
        self._write("products.json", self.products())
        return prod, created

    def delete_product(self, plu):
        found = self.products().pop(norm_plu(plu), None) is not None
        if found:
            self._write("products.json", self.products())
        return found

    def merge_products(self, remote):
        """Gabungkan produk dari sumber luar (Firebase): PLU yang sama ditimpa, lainnya dipertahankan."""
        for plu, p in remote.items():
            self.products()[plu] = p
        self._write("products.json", self.products())
        return len(remote)

    # ---- sesi stock opname
    def session(self):
        s = self._read("session.json", None)
        return s if isinstance(s, dict) and isinstance(s.get("items"), list) and s.get("id") else None

    def _save_session(self, s):
        self._write("session.json", s)
        if s.get("status") == "final":
            _atomic_write(self.history_dir / (s["id"] + ".json"), s)

    def adopt_session(self, s):
        self._save_session(s)

    def apply_setup(self, plus):
        """Simpan daftar item SO. OH diambil dari data produk saat ini; hasil hitung item yang
        tetap dipilih dipertahankan. Bila sesi sebelumnya sudah FINAL, dimulai sesi baru."""
        prods = self.products()
        chosen = sorted({norm_plu(p) for p in plus if norm_plu(p) in prods}, key=natkey)
        if not chosen:
            raise ValueError("Pilih minimal 1 produk")
        old = self.session()
        keep = {it["plu"]: it["counts"] for it in old["items"]} if old and old.get("status") == "open" else {}
        items = [{"plu": p, "desc": prods[p]["desc"], "oh": prods[p]["oh"],
                  "counts": list(keep.get(p, [None] * SLOTS))} for p in chosen]
        if old and old.get("status") == "open":
            sess = dict(old, items=items)
        else:
            sess = {"id": new_session_id(), "created": now_iso(), "status": "open",
                    "finalized": None, "items": items}
        self._save_session(sess)
        return sess

    def item(self, plu):
        s = self.session()
        return next((it for it in s["items"] if it["plu"] == norm_plu(plu)), None) if s else None

    def set_counts(self, plu, counts):
        s = self.session()
        if not s:
            raise ValueError("Belum ada setup item Stock Opname")
        if s.get("status") != "open":
            raise ValueError("Sesi sudah final. Tekan Revisi untuk membukanya kembali")
        it = next((x for x in s["items"] if x["plu"] == norm_plu(plu)), None)
        if it is None:
            raise ValueError("Produk tidak ada dalam sesi ini")
        vals = list(counts)
        if len(vals) > SLOTS:
            raise ValueError("Maksimal %d kolom isi" % SLOTS)
        vals += [None] * (SLOTS - len(vals))
        for v in vals:
            if v is not None and (not isinstance(v, (int, float)) or isinstance(v, bool) or v != v
                                  or v in (float("inf"), float("-inf")) or v < 0):
                raise ValueError("Hitungan harus angka 0 atau lebih")
        it["counts"] = [None if v is None else round(float(v), 3) for v in vals]
        self._save_session(s)
        return it

    def finalize(self):
        s = self.session()
        if not s or s.get("status") != "open":
            raise ValueError("Tidak ada sesi berjalan untuk disimpan")
        pending = [it for it in s["items"] if not item_calc(it)[0]]
        if pending:
            raise ValueError("%d produk belum dihitung" % len(pending))
        s["status"] = "final"
        s["finalized"] = now_iso()
        s["summary"] = summarize(s)
        self._save_session(s)
        return s

    def reopen(self):
        s = self.session()
        if not s or s.get("status") != "final":
            raise ValueError("Sesi belum final")
        s["status"] = "open"
        s["finalized"] = None
        s.pop("summary", None)
        self._save_session(s)
        return s

    # ---- pengaturan Firebase
    def config(self):
        c = self._read("config.json", {})
        return dict(DEFAULT_CONFIG, **{k: v for k, v in (c if isinstance(c, dict) else {}).items() if k in DEFAULT_CONFIG})

    def save_config(self, cfg):
        self._write("config.json", {k: cfg.get(k, DEFAULT_CONFIG[k]) for k in DEFAULT_CONFIG})


def init_storage(base):
    global BASE, STORE
    BASE = Path(base)
    STORE = Store(BASE)
    return STORE


# ============================================================ Firebase Realtime Database (REST)
class FirebaseError(Exception):
    pass


def fb_key(plu):
    """Kunci Firebase tidak boleh memuat . $ # [ ] / dan karakter kontrol: dikodekan %XX (bisa dibalik)."""
    if not plu:
        raise ValueError("kunci kosong")
    return re.sub(r"[.$#\[\]/%\x00-\x1f\x7f]", lambda m: "%%%02X" % ord(m.group()), plu)


def fb_unkey(key):
    return re.sub(r"%([0-9A-F]{2})", lambda m: chr(int(m.group(1), 16)), key)


def normalize_db_url(url):
    u = (url or "").strip()
    if not u:
        raise ValueError("URL Firebase belum diisi")
    if "://" not in u:
        u = "https://" + u
    p = urllib.parse.urlsplit(u)
    if p.scheme not in ("https", "http") or not p.netloc:
        raise ValueError("URL Firebase tidak valid")
    return "%s://%s" % (p.scheme, p.netloc)


def clean_root(root):
    r = "/".join(x for x in (root or "").replace("\\", "/").split("/") if x.strip()) or "stockopname"
    if re.search(r"[.$#\[\]\x00-\x1f]", r):
        raise ValueError("Path root tidak boleh memuat . $ # [ ]")
    return r


def make_ssl_context():
    """Android tidak punya daftar sertifikat CA bawaan: pakai certifi bila ada."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def product_to_fb(p):
    return {"plu": p["plu"], "desc": p["desc"], "oh": p["oh"], "updated": p.get("updated", "")}


def product_from_fb(key, d):
    if not isinstance(d, dict) or not d.get("desc") or not isinstance(d.get("oh"), (int, float)):
        return None
    plu = norm_plu(d.get("plu") or fb_unkey(key))
    return {"plu": plu, "desc": clean1(str(d["desc"])), "oh": float(d["oh"]), "updated": str(d.get("updated", ""))}


def session_to_fb(s):
    """Item disimpan sebagai objek (bukan array) agar nilai kosong tidak merusak indeks."""
    items = {}
    for i, it in enumerate(s["items"]):
        d, total, diff = item_calc(it)
        row = {"idx": i, "plu": it["plu"], "desc": it["desc"], "oh": it["oh"]}
        for n, c in enumerate(it["counts"], 1):
            if c is not None:
                row["c%d" % n] = c
        if d:
            row["total"], row["diff"] = total, diff
        items[fb_key(it["plu"])] = row
    out = {"id": s["id"], "created": s["created"], "status": s["status"], "items": items}
    if s.get("finalized"):
        out["finalized"] = s["finalized"]
    if s.get("summary"):
        out["summary"] = s["summary"]
    return out


def session_from_fb(d, sid):
    if not isinstance(d, dict):
        return None
    rows = []
    for key, r in (d.get("items") or {}).items():
        if not isinstance(r, dict) or not isinstance(r.get("oh"), (int, float)):
            continue
        counts = [r.get("c%d" % n) if isinstance(r.get("c%d" % n), (int, float)) else None for n in range(1, SLOTS + 1)]
        rows.append((r.get("idx", 0), {"plu": norm_plu(r.get("plu") or fb_unkey(key)), "desc": clean1(str(r.get("desc", ""))),
                                       "oh": float(r["oh"]), "counts": counts}))
    rows.sort(key=lambda t: (t[0], natkey(t[1]["plu"])))
    s = {"id": d.get("id") or sid, "created": d.get("created") or now_iso(),
         "status": "final" if d.get("status") == "final" else "open",
         "finalized": d.get("finalized"), "items": [r for _, r in rows]}
    if s["status"] == "final":
        s["summary"] = summarize(s)
    return s


class Firebase:
    def __init__(self, url, root="stockopname", auth="", timeout=15, ctx=None):
        self.base = normalize_db_url(url)
        self.root = clean_root(root)
        self.auth = (auth or "").strip()
        self.timeout = timeout
        self.ctx = ctx if ctx is not None else make_ssl_context()

    def endpoint(self, path, **params):
        full = "/".join(x for x in (self.root, path.strip("/")) if x)
        q = dict(params)
        if self.auth:
            q["auth"] = self.auth
        # safe="/" : tanda % di kunci ikut dikodekan (%25) agar server memulihkan kunci apa adanya
        return "%s/%s.json%s" % (self.base, urllib.parse.quote(full, safe="/"), ("?" + urllib.parse.urlencode(q)) if q else "")

    def request(self, method, path, data=None, **params):
        body = None if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.endpoint(path, **params), data=body, method=method,
                                     headers={"Content-Type": "application/json; charset=utf-8"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self.ctx) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = str(json.loads(e.read().decode("utf-8", "replace")).get("error", ""))[:120]
            except Exception:
                pass
            if e.code in (401, 403):
                raise FirebaseError("Akses ditolak (%d). Periksa token dan aturan (rules) database. %s" % (e.code, detail))
            if e.code == 404:
                raise FirebaseError("Database tidak ditemukan (404). Periksa URL Firebase.")
            if e.code >= 500:
                raise FirebaseError("Server Firebase bermasalah (%d). Coba lagi nanti." % e.code)
            raise FirebaseError("Permintaan ditolak Firebase (%d). %s" % (e.code, detail))
        except (urllib.error.URLError, socket.timeout, ssl.SSLError, OSError) as e:
            raise FirebaseError("Tidak dapat terhubung ke Firebase: %s" % getattr(e, "reason", e))
        return json.loads(raw.decode("utf-8")) if raw.strip() else None

    def get(self, path):
        return self.request("GET", path)

    def put(self, path, data):
        return self.request("PUT", path, data, print="silent")

    def delete(self, path):
        return self.request("DELETE", path, print="silent")

    def ping(self):
        stamp = now_iso()
        self.put("_meta", {"app": "stock-opname", "ping": stamp})
        got = self.get("_meta")
        if not isinstance(got, dict) or got.get("ping") != stamp:
            raise FirebaseError("Firebase merespons tidak sesuai. Periksa URL dan path root.")
        return True

    def put_product(self, p):
        self.put("products/" + fb_key(p["plu"]), product_to_fb(p))

    def delete_product(self, plu):
        self.delete("products/" + fb_key(norm_plu(plu)))

    def put_products(self, products):
        self.put("products", {fb_key(k): product_to_fb(v) for k, v in products.items()})

    def get_products(self):
        out = {}
        for key, d in (self.get("products") or {}).items():
            p = product_from_fb(key, d)
            if p:
                out[p["plu"]] = p
        return out

    def put_session(self, s):
        self.put("sessions/" + fb_key(s["id"]), session_to_fb(s))
        self.put("meta/active_session", s["id"])

    def get_active_session(self):
        sid = self.get("meta/active_session")
        if not sid or not isinstance(sid, str):
            return None
        return session_from_fb(self.get("sessions/" + fb_key(sid)), sid)


def make_client(cfg):
    return Firebase(cfg.get("url", ""), cfg.get("root", ""), cfg.get("auth", ""))


def sync_push_all(fb, store):
    """Kirim produk + sesi aktif. Produk kosong tidak dikirim (agar tidak menghapus data di Firebase)."""
    prods, sess = store.products(), store.session()
    if prods:
        fb.put_products(prods)
    if sess:
        fb.put_session(sess)
    return {"products": len(prods), "session": sess["id"] if sess else None}


def sync_pull_all(fb, store):
    """Ambil dari Firebase: produk digabung (Firebase menang pada PLU sama), sesi aktif diadopsi."""
    remote = fb.get_products()
    n = store.merge_products(remote) if remote else 0
    sess = fb.get_active_session()
    if sess:
        store.adopt_session(sess)
    return {"products": n, "session": sess["id"] if sess else None}


def run_async(fn, cb):
    """Jalankan fn di thread latar; cb(hasil, error) dipanggil di thread Kivy."""
    def work():
        try:
            res, err = fn(), None
        except Exception as e:  # noqa: BLE001 - dilaporkan ke antarmuka
            res, err = None, e
        Clock.schedule_once(lambda _dt: cb(res, err), 0)
    threading.Thread(target=work, daemon=True).start()


def set_sync_status(text):
    app = App.get_running_app()
    if app is not None:
        app.sync_status = text


def auto_sync(job, *args):
    """Kirim perubahan ke Firebase di latar belakang bila sinkron otomatis aktif.
    Gagal -> hanya mencatat status (aplikasi tetap bekerja lokal)."""
    cfg = STORE.config()
    if not (cfg["auto"] and cfg["url"]):
        return False
    try:
        fb = make_client(cfg)
    except ValueError as e:
        set_sync_status("Firebase: %s" % e)
        return False
    run_async(lambda: job(fb, *args),
              lambda _res, err: set_sync_status("Firebase: gagal, %s" % err if err
                                                else "Firebase: tersinkron %s" % datetime.now().strftime("%H:%M:%S")))
    return True


# ============================================================ gambar laporan PNG (Python murni)
_FONT = {}


def _font():
    """Muat font bitmap (fontdata.py): daftar piksel tak-nol per glyph, siap digambar."""
    if not _FONT:
        import fontdata
        w, h = fontdata.W, fontdata.H
        _FONT.update(w=w, h=h)
        for key, b64 in (("r", fontdata.REGULAR), ("b", fontdata.BOLD)):
            raw = zlib.decompress(base64.b64decode(b64))
            size = w * h
            _FONT[key] = [[(i % w, i // w, v) for i, v in enumerate(raw[g * size:(g + 1) * size]) if v]
                          for g in range(95)]
    return _FONT


def fit(s, n, tail=".."):
    """Teks aman untuk font ASCII: karakter lain jadi '?', lalu dipotong ke n karakter."""
    s = "".join(c if 32 <= ord(c) <= 126 else (" " if ord(c) < 32 else "?") for c in str(s))
    return s if len(s) <= n else s[:max(0, n - len(tail))] + tail


def fit_num(s, n):
    return s if len(s) <= n else s[:max(0, n - 1)] + "~"


class Canvas:
    def __init__(self, w, h, bg):
        self.w, self.h = w, h
        self.buf = bytearray(bytes(bg) * (w * h))

    def rect(self, x, y, w, h, color):
        x0, x1 = max(0, x), min(self.w, x + w)
        if x1 <= x0:
            return
        row = bytes(color) * (x1 - x0)
        for yy in range(max(0, y), min(self.h, y + h)):
            o = (yy * self.w + x0) * 3
            self.buf[o:o + 3 * (x1 - x0)] = row

    def text(self, x, y, s, fg, bg, bold=False):
        f = _font()
        glyphs, w = f["b" if bold else "r"], f["w"]
        lut = [bytes(bg[c] + (fg[c] - bg[c]) * a // 15 for c in range(3)) for a in range(16)]
        for ch in fit(s, 10 ** 6, ""):
            for gx, gy, a in glyphs[ord(ch) - 32]:
                px, py = x + gx, y + gy
                if 0 <= px < self.w and 0 <= py < self.h:
                    o = (py * self.w + px) * 3
                    self.buf[o:o + 3] = lut[a]
            x += w

    def rtext(self, xr, y, s, fg, bg, bold=False):
        self.text(xr - len(s) * _font()["w"], y, s, fg, bg, bold)

    def png(self):
        def chunk(t, d):
            return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
        stride = self.w * 3
        raw = b"".join(b"\x00" + bytes(self.buf[y * stride:(y + 1) * stride]) for y in range(self.h))
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# warna laporan (RGB)
C_NAVY, C_WHITE, C_INK, C_GRAY = (31, 58, 95), (255, 255, 255), (27, 36, 48), (91, 102, 118)
C_HEAD, C_LINE, C_ZEBRA, C_SUM = (230, 236, 245), (205, 213, 224), (246, 248, 251), (240, 244, 250)
C_BAD, C_WARN, C_OK = (180, 35, 24), (180, 83, 9), (27, 127, 59)
C_BAD_BG, C_WARN_BG, C_OK_BG = (253, 236, 236), (255, 244, 224), (236, 247, 238)
REPORT_COLS = [("desc", 308), ("oh", 98), ("c1", 84), ("c2", 84), ("c3", 84), ("c4", 84), ("c5", 84),
               ("tot", 112), ("dif", 112)]
REPORT_PAD = 28


def _dcolor(diff):
    return C_INK if diff is None else (C_BAD if diff < 0 else C_WARN if diff > 0 else C_OK)


def render_report(session, rows_per_page=20):
    """Tabel hasil SO sebagai daftar PNG (satu gambar per halaman, agar tetap terbaca di WhatsApp)."""
    f = _font()
    cw, ch = f["w"], f["h"]
    pad, width = REPORT_PAD, sum(w for _, w in REPORT_COLS) + 2 * REPORT_PAD
    row_h, head_h, th_h = 2 * ch + 14, 2 * ch + 40, ch + 18
    sum_h, tot_h, foot_h = 2 * ch + 38, ch + 24, ch + 30
    items = session["items"]
    pages = max(1, -(-len(items) // rows_per_page))
    sm = summarize(session)
    final = session.get("status") == "final"
    xs, acc = [], pad
    for _, w in REPORT_COLS:
        xs.append(acc)
        acc += w
    inner = width - 2 * pad
    out = []
    for pg in range(pages):
        chunk = items[pg * rows_per_page:(pg + 1) * rows_per_page]
        last = pg == pages - 1
        height = head_h + (sum_h if pg == 0 else 0) + th_h + row_h * len(chunk) + (tot_h if last else 0) + foot_h
        cv = Canvas(width, height, C_WHITE)
        # judul
        cv.rect(0, 0, width, head_h, C_NAVY)
        cv.text(pad, 16, "HASIL STOCK OPNAME" + ("" if final else " (SEMENTARA)"), C_WHITE, C_NAVY, True)
        cv.text(pad, 16 + ch + 8, fit("%s   %s" % (session["id"], session.get("finalized") or session["created"]), 60),
                (201, 214, 234), C_NAVY)
        cv.rtext(width - pad, 16, "Hal %d/%d" % (pg + 1, pages), C_WHITE, C_NAVY, True)
        y = head_h
        if pg == 0:  # ringkasan
            cv.rect(0, y, width, sum_h, C_SUM)
            cv.text(pad, y + 14, "Produk: %d   Sesuai: %d   Kurang: %d   Lebih: %d" %
                    (sm["n"], sm["ok"], sm["short"], sm["over"]), C_INK, C_SUM, True)
            line = "Total OH: %s   Total Fisik: %s   Selisih: " % (fmt_qty(sm["oh_total"]), fmt_qty(sm["fisik_total"]))
            cv.text(pad, y + 14 + ch + 6, line, C_INK, C_SUM)
            cv.text(pad + len(line) * cw, y + 14 + ch + 6, fmt_diff(sm["diff_total"]), _dcolor(sm["diff_total"]), C_SUM, True)
            y += sum_h
        # kepala tabel
        cv.rect(pad, y, inner, th_h, C_HEAD)
        titles = {"desc": "PLU / Deskripsi", "oh": "OH", "tot": "T.Fisik", "dif": "Selisih"}
        for (key, w), x in zip(REPORT_COLS, xs):
            t = titles.get(key, key[1:])
            if key == "desc":
                cv.text(x + 8, y + 9, t, C_INK, C_HEAD, True)
            else:
                cv.rtext(x + w - 10, y + 9, t, C_INK, C_HEAD, True)
        y += th_h
        top = y
        for i, it in enumerate(chunk):
            done, total, diff = item_calc(it)
            bg = C_ZEBRA if (pg * rows_per_page + i) % 2 else C_WHITE
            if done:
                bg = C_BAD_BG if diff < 0 else C_WARN_BG if diff > 0 else C_OK_BG
            cv.rect(pad, y, inner, row_h, bg)
            cv.text(xs[0] + 8, y + 7, fit(it["plu"], (REPORT_COLS[0][1] - 16) // cw), C_INK, bg, True)
            cv.text(xs[0] + 8, y + 7 + ch, fit(it["desc"], (REPORT_COLS[0][1] - 16) // cw), C_GRAY, bg)
            vy = y + (row_h - ch) // 2
            cells = [("oh", fmt_qty(it["oh"]), False, C_INK)]
            cells += [("c%d" % n, fmt_qty(c), False, C_INK) for n, c in enumerate(it["counts"], 1)]
            cells += [("tot", fmt_qty(total), True, C_INK), ("dif", fmt_diff(diff), True, _dcolor(diff))]
            for (key, txt, bold, col), (k2, w), x in zip(cells, REPORT_COLS[1:], xs[1:]):
                cv.rtext(x + w - 10, vy, fit_num(txt, (w - 14) // cw), col, bg, bold)
            cv.rect(pad, y + row_h - 1, inner, 1, C_LINE)
            y += row_h
        if last:  # baris total
            cv.rect(pad, y, inner, tot_h, C_HEAD)
            cv.text(xs[0] + 8, y + 12, "TOTAL (%d produk)" % sm["n"], C_INK, C_HEAD, True)
            for key, txt, col in (("oh", fmt_qty(sm["oh_total"]), C_INK), ("tot", fmt_qty(sm["fisik_total"]), C_INK),
                                  ("dif", fmt_diff(sm["diff_total"]), _dcolor(sm["diff_total"]))):
                idx = [k for k, _ in REPORT_COLS].index(key)
                cv.rtext(xs[idx] + REPORT_COLS[idx][1] - 10, y + 12, fit_num(txt, (REPORT_COLS[idx][1] - 14) // cw),
                         col, C_HEAD, True)
            y += tot_h
        # garis kolom
        for x in xs[1:] + [pad + inner]:
            cv.rect(x - 1, top - th_h, 1, y - top + th_h, C_LINE)
        cv.rect(pad, top - th_h, 1, y - top + th_h, C_LINE)
        cv.text(pad, height - foot_h + 10, "Dibuat dengan aplikasi Stock Opname   %s" % now_iso(), C_GRAY, C_WHITE)
        out.append(cv.png())
    return out


def export_report(store, session, rows_per_page=20):
    """Simpan PNG ke folder exports dan kembalikan daftar path-nya."""
    for old in store.export_dir.glob(session["id"] + "_*.png"):
        old.unlink()
    paths = []
    for i, data in enumerate(render_report(session, rows_per_page), 1):
        p = store.export_dir / ("%s_%02d.png" % (session["id"], i))
        p.write_bytes(data)
        paths.append(p)
    return paths


# ============================================================ kirim ke WhatsApp (Android)
def ensure_write_permission(then, denied):
    """Android 9 ke bawah butuh izin tulis untuk menyalin gambar ke penyimpanan bersama.
    Android 10+ tidak membutuhkannya."""
    try:
        from jnius import autoclass
        sdk = int(autoclass("android.os.Build$VERSION").SDK_INT)
    except Exception:
        sdk = 99
    if sdk >= 29:
        return then()
    from android.permissions import Permission, request_permissions
    request_permissions([Permission.WRITE_EXTERNAL_STORAGE],
                        lambda _perms, grants: then() if grants and all(grants) else denied())


def android_share(paths, package="com.whatsapp"):
    """Salin PNG ke penyimpanan bersama (Pictures) lalu buka WhatsApp langsung; bila WhatsApp
    tidak ada, tampilkan pilihan aplikasi. Mengembalikan ShareSheet (simpan referensinya)."""
    from androidstorage4kivy import ShareSheet, SharedStorage
    ss, sheet = SharedStorage(), ShareSheet()
    shared = [x for x in (ss.copy_to_shared(str(p)) for p in paths) if x]
    if not shared:
        raise RuntimeError("gagal menyalin gambar ke penyimpanan bersama")

    def send(app):
        if len(shared) == 1:
            sheet.share_file(shared[0], app=app)
        else:
            sheet.share_file_list(shared, app=app)
    try:
        send(package)
    except Exception:
        send(None)
    return sheet


def share_images(paths, package="com.whatsapp", on_done=None):
    """on_done(berhasil, pesan). Di komputer hanya melaporkan lokasi berkas PNG."""
    on_done = on_done or (lambda ok, msg: None)
    where = "\n".join(str(p) for p in paths)
    if platform != "android":
        return on_done(False, "Gambar disimpan di:\n" + where)

    def go():
        try:
            holder = android_share(paths, package)
            app = App.get_running_app()
            if app is not None:
                app._sheet = holder
            on_done(True, "WhatsApp dibuka (%d gambar)." % len(paths))
        except Exception as e:  # noqa: BLE001
            on_done(False, "Gagal membuka WhatsApp: %s\nGambar tersimpan di:\n%s" % (e, where))
    ensure_write_permission(go, lambda: on_done(False, "Izin penyimpanan ditolak. Gambar tersimpan di:\n" + where))


# ============================================================ antarmuka
def go(name):
    App.get_running_app().root.current = name


def hexcol(diff):
    return "1b7f3b" if diff == 0 else ("b42318" if diff < 0 else "b45309")


def popup(title, msg, buttons, height=dp(230)):
    """buttons = [(label, callback|None, primary?)]"""
    box = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(14))
    lbl = Label(text=msg, markup=True, color=INK, halign="center", valign="middle")
    lbl.bind(width=lambda w, x: setattr(w, "text_size", (x, None)))
    box.add_widget(lbl)
    row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
    pop = Popup(title=title, content=box, auto_dismiss=False, size_hint=(None, None),
                size=(min(dp(460), Window.width * 0.92), height),
                background="", background_color=SURFACE, title_color=INK, separator_color=ACCENT)
    OPEN_POPUPS.append(pop)
    pop.bind(on_dismiss=lambda *_: OPEN_POPUPS.remove(pop) if pop in OPEN_POPUPS else None)
    for label, cb, primary in buttons:
        b = Button(text=label, bold=True, background_normal="", background_down="",
                   background_color=ACCENT if primary else (0.9, 0.92, 0.95, 1),
                   color=SURFACE if primary else INK)

        def _click(_, cb=cb):
            pop.dismiss()
            if cb:
                cb()
        b.bind(on_release=_click)
        row.add_widget(b)
    box.add_widget(row)
    pop.open()
    return pop


def product_row(p, selected=None):
    mark = "   [color=3b49df][b]DIPILIH[/b][/color]" if selected else ""
    return {"plu": p["plu"], "sel": bool(selected),
            "text": "[b]%s[/b]  %s\nOH: %s%s" % (esc(p["plu"]), esc(p["desc"]), fmt_qty(p["oh"]), mark)}


def so_rows(session, query=""):
    """Baris tabel Stock Opname: PLU/Deskripsi | OH | 1..5 | Total Fisik | Selisih."""
    q = query.strip().lower()
    rows = []
    for it in session["items"]:
        if q and q not in it["plu"].lower() and q not in it["desc"].lower():
            continue
        done, total, diff = item_calc(it)
        if not done:
            bg, dc = [1, 1, 1, 1], list(INK)
        elif diff < 0:
            bg, dc = [1.0, 0.93, 0.93, 1], list(BAD)
        elif diff > 0:
            bg, dc = [1.0, 0.96, 0.88, 1], list(WARN)
        else:
            bg, dc = [0.92, 0.98, 0.93, 1], list(OKC)
        row = {"plu": it["plu"], "title": "[b]%s[/b]\n%s" % (esc(it["plu"]), esc(it["desc"])),
               "oh": fmt_qty(it["oh"]), "total": fmt_qty(total), "diff": fmt_diff(diff), "dcolor": dc, "bg": bg}
        for n, c in enumerate(it["counts"], 1):
            row["c%d" % n] = fmt_qty(c)
        rows.append(row)
    return rows


class CountEditor:
    """Popup input hitungan: 5 kolom isi, Total Fisik dan Selisih dihitung langsung."""

    def __init__(self, screen, plu, focus=1):
        self.screen, self.plu = screen, plu
        self.item = STORE.item(plu)
        it = self.item
        box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        box.add_widget(Label(text="[b]%s[/b]\n%s\nOH (stok sistem): [b]%s[/b]" % (esc(it["plu"]), esc(it["desc"]), fmt_qty(it["oh"])),
                             markup=True, color=INK, halign="center", valign="middle", size_hint_y=None, height=dp(78)))
        head = BoxLayout(size_hint_y=None, height=dp(22), spacing=dp(6))
        row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
        self.inputs = []
        for n in range(1, SLOTS + 1):
            head.add_widget(Label(text=str(n), color=(0.42, 0.47, 0.55, 1), bold=True))
            ti = TextInput(text=fmt_qty(it["counts"][n - 1]), multiline=False, input_filter=qty_filter,
                           input_type="number", hint_text="-", halign="center", write_tab=False, font_size=dp(18))
            ti.bind(text=lambda *_: self.refresh())
            self.inputs.append(ti)
            row.add_widget(ti)
        box.add_widget(head)
        box.add_widget(row)
        self.info = Label(markup=True, color=INK, halign="center", valign="middle", size_hint_y=None, height=dp(56))
        box.add_widget(self.info)
        btns = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        for label, primary, fn in (("Batal", False, lambda: self.popup.dismiss()),
                                   ("Simpan", True, lambda: self.save(False)),
                                   ("Simpan & Berikutnya", True, lambda: self.save(True))):
            b = Button(text=label, bold=True, background_normal="", background_down="",
                       background_color=ACCENT if primary else (0.9, 0.92, 0.95, 1),
                       color=SURFACE if primary else INK, font_size=dp(13))
            b.bind(on_release=lambda _b, fn=fn: fn())
            btns.add_widget(b)
        box.add_widget(btns)
        self.popup = Popup(title="Input hitungan", content=box, auto_dismiss=False, size_hint=(None, None),
                           size=(min(dp(460), Window.width * 0.96), dp(380)), background="",
                           background_color=SURFACE, title_color=INK, separator_color=ACCENT)
        OPEN_POPUPS.append(self.popup)
        self.popup.bind(on_dismiss=lambda *_: OPEN_POPUPS.remove(self.popup) if self.popup in OPEN_POPUPS else None)
        self.refresh()
        self.popup.open()
        Clock.schedule_once(lambda _dt: setattr(self.inputs[max(1, min(SLOTS, focus)) - 1], "focus", True), 0.2)

    def values(self):
        return [parse_qty(ti.text, allow_negative=False) for ti in self.inputs]

    def refresh(self):
        try:
            vals = self.values()
        except ValueError as e:
            self.info.text = "[color=b42318]%s[/color]" % esc(str(e))
            return None
        done, total, diff = item_calc({"counts": vals, "oh": self.item["oh"]})
        self.info.text = ("Total Fisik: [b]%s[/b]      Selisih: [b][color=%s]%s[/color][/b]" % (fmt_qty(total), hexcol(diff), fmt_diff(diff))
                          if done else "Isi minimal satu kolom (isi 0 bila tidak ada stok)")
        return vals

    def save(self, advance=False):
        try:
            vals = self.values()
            STORE.set_counts(self.plu, vals)
        except ValueError as e:
            self.info.text = "[color=b42318]%s[/color]" % esc(str(e))
            return False
        self.popup.dismiss()
        self.screen.reload(keep_scroll=True)
        if advance:
            nxt = self.screen.next_plu(self.plu)
            if nxt:
                self.screen.editor = CountEditor(self.screen, nxt)
        return True


class HomeScreen(Screen):
    def refresh(self):
        st, cfg = STORE, STORE.config()
        s = st.session()
        lines = ["Produk terdaftar: [b]%d[/b]" % len(st.products())]
        if s:
            sm = summarize(s)
            lines.append("Sesi [b]%s[/b]: %d/%d dihitung (%s)" % (esc(s["id"]), sm["done"], sm["n"],
                                                                "FINAL" if s["status"] == "final" else "berjalan"))
        else:
            lines.append("Belum ada item Stock Opname (buka Setting Item Stock Opname)")
        lines.append("Firebase: " + ("sinkron otomatis" if cfg["auto"] and cfg["url"] else
                                     "diatur, kirim manual" if cfg["url"] else "tidak dipakai (data tersimpan lokal)"))
        status = getattr(App.get_running_app(), "sync_status", "")
        if status:
            lines.append("[color=6b788c]%s[/color]" % esc(status))
        self.ids.status.text = "\n".join(lines)


class ProductsScreen(Screen):
    editing = None

    def qty_filter(self, substring, from_undo):
        return oh_filter(substring, from_undo)

    def refresh(self):
        items = STORE.product_list(self.ids.q.text)
        total = len(STORE.products())
        self.ids.rv.data = [product_row(p) for p in items]
        self.ids.info.text = "%d produk%s" % (total, "" if len(items) == total else " (tampil %d)" % len(items))

    def pick(self, plu):
        p = STORE.products().get(plu)
        if not p:
            return
        self.editing = plu
        self.ids.f_plu.text, self.ids.f_desc.text, self.ids.f_oh.text = p["plu"], p["desc"], fmt_qty(p["oh"])
        self.ids.f_plu.readonly = True  # PLU tidak diubah; untuk mengganti PLU: hapus lalu input baru
        self.ids.b_save.text = "Perbarui"
        self.ids.b_del.disabled = False
        self.ids.msg.text = "Mengubah PLU [b]%s[/b]" % esc(plu)

    def clear_form(self):
        self.editing = None
        self.ids.f_plu.text = self.ids.f_desc.text = self.ids.f_oh.text = ""
        self.ids.f_plu.readonly = False
        self.ids.b_save.text = "Simpan"
        self.ids.b_del.disabled = True
        self.ids.msg.text = ""

    def save(self):
        try:
            prod, created = STORE.upsert_product(self.ids.f_plu.text, self.ids.f_desc.text, self.ids.f_oh.text,
                                                 allow_update=self.editing is not None)
        except ValueError as e:
            self.ids.msg.text = "[color=b42318]%s[/color]" % esc(str(e))
            return
        auto_sync(lambda fb, p: fb.put_product(p), prod)
        self.clear_form()
        self.ids.msg.text = "[color=1b7f3b]%s %s[/color]" % ("Tersimpan:" if created else "Diperbarui:", esc(prod["plu"]))
        self.refresh()

    def ask_delete(self):
        if not self.editing:
            return
        plu = self.editing
        popup("Hapus produk", "Hapus [b]%s[/b] dari data produk?\n(Sesi Stock Opname yang berjalan tidak berubah.)" % esc(plu),
              [("Batal", None, False), ("Ya, hapus", lambda: self._delete(plu), True)], height=dp(220))

    def _delete(self, plu):
        STORE.delete_product(plu)
        auto_sync(lambda fb, p: fb.delete_product(p), plu)
        self.clear_form()
        self.refresh()


class SetupScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.sel = set()

    def load(self):
        s = STORE.session()
        self.sel = {it["plu"] for it in s["items"]} if s else set()
        self.refresh()

    def _count(self):
        return len(self.sel & set(STORE.products()))

    def refresh(self):
        items = STORE.product_list(self.ids.q.text)
        self.ids.rv.data = [product_row(p, p["plu"] in self.sel) for p in items]
        self.ids.info.text = "Dipilih [b]%d[/b] dari %d produk" % (self._count(), len(STORE.products()))

    def toggle(self, plu):
        self.sel ^= {plu}
        for row in self.ids.rv.data:
            if row["plu"] == plu:
                row.update(product_row(STORE.products()[plu], plu in self.sel))
                break
        self.ids.rv.refresh_from_data()
        self.ids.info.text = "Dipilih [b]%d[/b] dari %d produk" % (self._count(), len(STORE.products()))

    def select_all(self):
        self.sel |= {p["plu"] for p in STORE.product_list(self.ids.q.text)}
        self.refresh()

    def clear_all(self):
        self.sel -= {p["plu"] for p in STORE.product_list(self.ids.q.text)}
        self.refresh()

    def ask_save(self):
        chosen = sorted(self.sel & set(STORE.products()), key=natkey)
        if not chosen:
            return popup("Belum ada item", "Pilih minimal satu produk untuk Stock Opname.", [("OK", None, True)], height=dp(190))
        old = STORE.session()
        note = ""
        if old and old["status"] == "final":
            note = "\n\nSesi sebelumnya sudah FINAL. Ini akan memulai sesi BARU (semua hitungan kosong)."
        elif old:
            counted = [it["plu"] for it in old["items"] if item_calc(it)[0]]
            dropped = [p for p in counted if p not in chosen]
            kept = len(counted) - len(dropped)
            if kept:
                note += "\n\n%d item sudah punya hasil hitung dan dipertahankan." % kept
            if dropped:
                note += "\n[color=b42318]%d item yang sudah dihitung dikeluarkan dari sesi.[/color]" % len(dropped)
            note += "\nOH diperbarui dari data produk."
        popup("Konfirmasi setup", "Simpan [b]%d[/b] item untuk Stock Opname?%s" % (len(chosen), note),
              [("Batal", None, False), ("Ya, simpan", lambda: self._save(chosen), True)], height=dp(280 if note else 190))

    def _save(self, chosen):
        try:
            sess = STORE.apply_setup(chosen)
        except ValueError as e:
            return popup("Gagal", esc(str(e)), [("OK", None, True)], height=dp(190))
        auto_sync(lambda fb, s: fb.put_session(s), sess)
        popup("Setup tersimpan", "[b]%d[/b] item siap di-Stock Opname.\nNo. sesi: %s" % (len(sess["items"]), esc(sess["id"])),
              [("Tutup", None, False), ("Buka Stock Opname", lambda: go("so"), True)], height=dp(210))


class SOScreen(Screen):
    def reload(self, keep_scroll=False):
        s = STORE.session()
        rv = self.ids.rv
        if not s:
            self.ids.progress.text = "Belum ada item Stock Opname.\nBuka General > Setting Item Stock Opname."
            rv.data = []
            self._buttons(None)
            return
        sm = summarize(s)
        self.ids.progress.text = ("[b]%s[/b]  (%s)\nDihitung [b]%d/%d[/b]   Sesuai %d   Kurang %d   Lebih %d"
                                  % (esc(s["id"]), "FINAL" if s["status"] == "final" else "berjalan", sm["done"], sm["n"],
                                     sm["ok"], sm["short"], sm["over"]))
        sy = rv.scroll_y
        rv.data = so_rows(s, self.ids.q.text)
        if keep_scroll:
            Clock.schedule_once(lambda _dt: setattr(rv, "scroll_y", sy), 0)
        self._buttons(s)

    def _buttons(self, s):
        final = bool(s and s["status"] == "final")
        self.ids.b_rev.disabled = not final
        self.ids.b_wa.disabled = not final
        self.ids.b_fin.disabled = s is None or final

    def next_plu(self, plu):
        order = [r["plu"] for r in so_rows(STORE.session(), self.ids.q.text)]
        return order[order.index(plu) + 1] if plu in order and order.index(plu) + 1 < len(order) else None

    def edit(self, plu, col=1):
        s = STORE.session()
        if not s:
            return None
        if s["status"] != "open":
            return popup("Sesi sudah final", "Hasil sudah disimpan. Tekan [b]Revisi[/b] bila perlu mengubahnya.",
                         [("OK", None, True)], height=dp(200))
        self.editor = CountEditor(self, plu, col)

    def finish(self):
        s = STORE.session()
        if not s or s["status"] != "open":
            return
        sm = summarize(s)
        if sm["done"] < sm["n"]:
            todo = [it["plu"] for it in s["items"] if not item_calc(it)[0]]
            return popup("Belum lengkap", "Masih [b]%d[/b] produk belum dihitung:\n%s%s" %
                         (len(todo), ", ".join(esc(x) for x in todo[:6]), " ..." if len(todo) > 6 else ""),
                         [("OK", None, True)], height=dp(230))
        msg = ("Semua [b]%d[/b] produk sudah dihitung.\nSesuai: [b]%d[/b]   Kurang: [b]%d[/b]   Lebih: [b]%d[/b]\n"
               "Total selisih: [b][color=%s]%s[/color][/b]\n\nSimpan hasil dan kirim ke WhatsApp (PNG)?"
               % (sm["n"], sm["ok"], sm["short"], sm["over"], hexcol(sm["diff_total"]), fmt_diff(sm["diff_total"])))
        popup("Konfirmasi Stock Opname", msg, [("Batal", None, False), ("Ya, simpan & kirim", self._confirm, True)],
              height=dp(300))

    def _confirm(self):
        try:
            s = STORE.finalize()
        except ValueError as e:
            return popup("Gagal menyimpan", esc(str(e)), [("OK", None, True)], height=dp(200))
        auto_sync(lambda fb, sess: fb.put_session(sess), s)
        self.reload()
        self.share()

    def share(self):
        s = STORE.session()
        if not s or s["status"] != "final":
            return
        try:
            paths = export_report(STORE, s)
        except Exception as e:  # noqa: BLE001
            return popup("Gagal membuat gambar", esc(str(e)[:150]), [("OK", None, True)], height=dp(200))
        share_images(paths, STORE.config()["wa"], self._shared)

    def _shared(self, ok, msg):
        if not ok:
            popup("Laporan PNG", esc(msg), [("OK", None, True)], height=dp(270))

    def ask_reopen(self):
        popup("Buka kembali", "Buka sesi yang sudah final untuk direvisi?\nHasil final akan kembali berstatus berjalan.",
              [("Batal", None, False), ("Ya, buka", self._reopen, True)], height=dp(220))

    def _reopen(self):
        try:
            s = STORE.reopen()
        except ValueError:
            return
        auto_sync(lambda fb, sess: fb.put_session(sess), s)
        self.reload()


class FirebaseScreen(Screen):
    def load(self):
        c = STORE.config()
        self.ids.url.text, self.ids.rootpath.text, self.ids.auth.text = c["url"], c["root"], c["auth"]
        self.ids.auto.active = bool(c["auto"])
        self.ids.msg.text = ""

    def cfg(self):
        return {"url": self.ids.url.text.strip(), "root": self.ids.rootpath.text.strip() or "stockopname",
                "auth": self.ids.auth.text.strip(), "auto": bool(self.ids.auto.active), "wa": STORE.config()["wa"]}

    def save(self):
        c = self.cfg()
        try:
            if c["url"]:
                normalize_db_url(c["url"])
            clean_root(c["root"])
        except ValueError as e:
            self.ids.msg.text = "[color=b42318]%s[/color]" % esc(str(e))
            return False
        STORE.save_config(c)
        hint = ("\nURL kosong: aplikasi berjalan lokal saja (tanpa Firebase)." if not c["url"] else
                "\nTekan [b]Kirim semua[/b] sekali untuk mengunggah data yang sudah ada." if c["auto"] else "")
        self.ids.msg.text = "[color=1b7f3b]Pengaturan tersimpan.[/color]" + hint
        return True

    def _run(self, busy, job, ok_text):
        if not self.save():
            return
        try:
            fb = make_client(STORE.config())
        except ValueError as e:
            self.ids.msg.text = "[color=b42318]%s[/color]" % esc(str(e))
            return
        self.ids.msg.text = busy
        run_async(lambda: job(fb), lambda res, err: self._done(res, err, ok_text))

    def _done(self, res, err, ok_text):
        if err:
            self.ids.msg.text = "[color=b42318]Gagal: %s[/color]" % esc(str(err)[:300])
            set_sync_status("Firebase: gagal, %s" % str(err)[:80])
        else:
            self.ids.msg.text = "[color=1b7f3b]%s[/color]" % esc(ok_text(res))
            set_sync_status("Firebase: tersinkron %s" % datetime.now().strftime("%H:%M:%S"))

    def test(self):
        self._run("Menguji koneksi...", lambda fb: fb.ping(), lambda r: "Koneksi berhasil: baca dan tulis ke database OK.")

    def push(self):
        self._run("Mengirim data...", lambda fb: sync_push_all(fb, STORE),
                  lambda r: "Terkirim: %d produk, sesi %s." % (r["products"], r["session"] or "-"))

    def ask_pull(self):
        popup("Ambil dari Firebase", "Produk dari Firebase digabung ke data lokal (PLU yang sama ditimpa).\n"
              "Sesi Stock Opname aktif di Firebase akan [b]menggantikan[/b] sesi lokal.\n\nLanjutkan?",
              [("Batal", None, False), ("Ya, ambil", self._pull, True)], height=dp(290))

    def _pull(self):
        self._run("Mengambil data...", lambda fb: sync_pull_all(fb, STORE),
                  lambda r: "Diambil: %d produk, sesi %s." % (r["products"], r["session"] or "-"))


KV = """
#:import dp kivy.metrics.dp
#:import sp kivy.metrics.sp
#:set INK (0.106, 0.141, 0.188, 1)
#:set MUTED (0.42, 0.47, 0.55, 1)
#:set ACCENT (0.231, 0.286, 0.875, 1)
#:set W_DESC 150
#:set W_OH 48
#:set W_CNT 46
#:set W_TOT 58
#:set W_DIF 58
#:set W_TABLE 544

<Btn@Button>:
    background_normal: ''
    background_down: ''
    background_color: ACCENT
    color: 1, 1, 1, 1
    bold: True
    size_hint_y: None
    height: dp(48)

<Quiet@Button>:
    background_normal: ''
    background_down: ''
    background_color: 1, 1, 1, 1
    color: ACCENT
    bold: True
    size_hint_y: None
    height: dp(48)

<Danger@Button>:
    background_normal: ''
    background_down: ''
    background_color: 0.78, 0.22, 0.27, 1
    color: 1, 1, 1, 1
    bold: True
    size_hint_y: None
    height: dp(48)

<Title@Label>:
    color: INK
    bold: True
    font_size: sp(22)
    halign: 'left'
    valign: 'middle'
    text_size: self.size

<Section@Label>:
    color: MUTED
    bold: True
    font_size: sp(13)
    halign: 'left'
    valign: 'bottom'
    text_size: self.size
    size_hint_y: None
    height: dp(30)

<Info@Label>:
    color: MUTED
    markup: True
    halign: 'left'
    valign: 'top'
    size_hint_y: None
    text_size: self.width, None
    height: self.texture_size[1] + dp(8)

<Field@TextInput>:
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
    size_hint_y: None
    height: dp(46)

<ProdRow@Button>:
    plu: ''
    sel: False
    markup: True
    background_normal: ''
    background_down: ''
    background_color: (0.86, 0.89, 1, 1) if self.sel else (1, 1, 1, 1)
    color: INK
    font_size: sp(14)
    halign: 'left'
    valign: 'middle'
    size_hint_y: None
    height: dp(58)
    text_size: self.width - dp(24), self.height
    on_release: app.pick_product(self.plu)

<SelRow@Button>:
    plu: ''
    sel: False
    markup: True
    background_normal: ''
    background_down: ''
    background_color: (0.86, 0.89, 1, 1) if self.sel else (1, 1, 1, 1)
    color: INK
    font_size: sp(14)
    halign: 'left'
    valign: 'middle'
    size_hint_y: None
    height: dp(58)
    text_size: self.width - dp(24), self.height
    on_release: app.toggle_setup(self.plu)

<HCell@Label>:
    color: 1, 1, 1, 1
    bold: True
    font_size: sp(12)
    halign: 'center'
    valign: 'middle'
    text_size: self.size
    size_hint_x: None

<Cell@Label>:
    color: INK
    font_size: sp(13)
    size_hint_x: None

<CountCell@Button>:
    background_normal: ''
    background_down: ''
    background_color: 0, 0, 0, 0
    color: INK
    font_size: sp(13)
    size_hint_x: None
    width: dp(W_CNT)
    canvas.after:
        Color:
            rgba: 0.82, 0.86, 0.92, 1
        Line:
            rectangle: self.x, self.y, self.width, self.height
            width: 1

<SOHeader@BoxLayout>:
    size_hint_y: None
    height: dp(40)
    canvas.before:
        Color:
            rgba: ACCENT
        Rectangle:
            pos: self.pos
            size: self.size
    HCell:
        text: 'PLU / Deskripsi'
        width: dp(W_DESC)
    HCell:
        text: 'OH'
        width: dp(W_OH)
    HCell:
        text: '1'
        width: dp(W_CNT)
    HCell:
        text: '2'
        width: dp(W_CNT)
    HCell:
        text: '3'
        width: dp(W_CNT)
    HCell:
        text: '4'
        width: dp(W_CNT)
    HCell:
        text: '5'
        width: dp(W_CNT)
    HCell:
        text: 'Total' + chr(10) + 'Fisik'
        width: dp(W_TOT)
    HCell:
        text: 'Selisih'
        width: dp(W_DIF)

<SORow@BoxLayout>:
    plu: ''
    title: ''
    oh: ''
    c1: ''
    c2: ''
    c3: ''
    c4: ''
    c5: ''
    total: ''
    diff: ''
    dcolor: INK
    bg: 1, 1, 1, 1
    size_hint_y: None
    height: dp(52)
    canvas.before:
        Color:
            rgba: root.bg
        Rectangle:
            pos: self.pos
            size: self.size
    Button:
        text: root.title
        markup: True
        size_hint_x: None
        width: dp(W_DESC)
        halign: 'left'
        valign: 'middle'
        font_size: sp(12)
        text_size: self.width - dp(8), self.height
        background_normal: ''
        background_down: ''
        background_color: 0, 0, 0, 0
        color: INK
        on_release: app.edit_counts(root.plu, 1)
    Cell:
        text: root.oh
        width: dp(W_OH)
    CountCell:
        text: root.c1
        on_release: app.edit_counts(root.plu, 1)
    CountCell:
        text: root.c2
        on_release: app.edit_counts(root.plu, 2)
    CountCell:
        text: root.c3
        on_release: app.edit_counts(root.plu, 3)
    CountCell:
        text: root.c4
        on_release: app.edit_counts(root.plu, 4)
    CountCell:
        text: root.c5
        on_release: app.edit_counts(root.plu, 5)
    Cell:
        text: root.total
        bold: True
        width: dp(W_TOT)
    Cell:
        text: root.diff
        bold: True
        color: root.dcolor
        width: dp(W_DIF)

<HomeScreen>:
    name: 'home'
    on_pre_enter: root.refresh()
    BoxLayout:
        orientation: 'vertical'
        padding: dp(16)
        spacing: dp(10)
        Title:
            text: 'Stock Opname'
            size_hint_y: None
            height: dp(48)
        Info:
            id: status
            text: ''
            color: INK
        Section:
            text: 'GENERAL'
        Btn:
            text: 'Input SKU'
            on_release: app.go('products')
        Btn:
            text: 'Setting Item Stock Opname'
            on_release: app.go('setup')
        Section:
            text: 'STOCK OPNAME'
        Btn:
            text: 'Stock Opname'
            on_release: app.go('so')
        Widget:
        Quiet:
            text: 'Firebase (opsional)'
            on_release: app.go('firebase')

<ProductsScreen>:
    name: 'products'
    on_pre_enter: root.refresh()
    BoxLayout:
        orientation: 'vertical'
        padding: dp(12)
        spacing: dp(8)
        BoxLayout:
            size_hint_y: None
            height: dp(48)
            spacing: dp(8)
            Quiet:
                text: 'Kembali'
                size_hint_x: None
                width: dp(100)
                on_release: app.go('home')
            Title:
                text: 'Input SKU'
        Field:
            id: f_plu
            hint_text: 'PLU / SKU'
        Field:
            id: f_desc
            hint_text: 'Deskripsi produk'
        Field:
            id: f_oh
            hint_text: 'OH (stok sistem)'
            input_filter: root.qty_filter
        Info:
            id: msg
            text: ''
        BoxLayout:
            size_hint_y: None
            height: dp(48)
            spacing: dp(8)
            Btn:
                id: b_save
                text: 'Simpan'
                on_release: root.save()
            Quiet:
                text: 'Baru'
                on_release: root.clear_form()
            Danger:
                id: b_del
                text: 'Hapus'
                disabled: True
                on_release: root.ask_delete()
        Field:
            id: q
            hint_text: 'Cari PLU / deskripsi...'
            on_text: root.refresh()
        Info:
            id: info
            text: ''
        RecycleView:
            id: rv
            viewclass: 'ProdRow'
            bar_width: dp(6)
            RecycleBoxLayout:
                default_size: None, None
                default_size_hint: 1, None
                size_hint_y: None
                height: self.minimum_height
                orientation: 'vertical'
                spacing: dp(2)

<SetupScreen>:
    name: 'setup'
    on_pre_enter: root.load()
    BoxLayout:
        orientation: 'vertical'
        padding: dp(12)
        spacing: dp(8)
        BoxLayout:
            size_hint_y: None
            height: dp(48)
            spacing: dp(8)
            Quiet:
                text: 'Kembali'
                size_hint_x: None
                width: dp(100)
                on_release: app.go('home')
            Title:
                text: 'Setting Item SO'
        Info:
            text: 'Ketuk produk untuk memilih item yang harus di-Stock Opname.'
        Field:
            id: q
            hint_text: 'Cari PLU / deskripsi...'
            on_text: root.refresh()
        BoxLayout:
            size_hint_y: None
            height: dp(48)
            spacing: dp(8)
            Quiet:
                text: 'Pilih semua'
                on_release: root.select_all()
            Quiet:
                text: 'Kosongkan'
                on_release: root.clear_all()
        Info:
            id: info
            text: ''
            color: INK
        RecycleView:
            id: rv
            viewclass: 'SelRow'
            bar_width: dp(6)
            RecycleBoxLayout:
                default_size: None, None
                default_size_hint: 1, None
                size_hint_y: None
                height: self.minimum_height
                orientation: 'vertical'
                spacing: dp(2)
        Btn:
            text: 'Simpan Setup'
            on_release: root.ask_save()

<SOScreen>:
    name: 'so'
    on_pre_enter: root.reload()
    BoxLayout:
        orientation: 'vertical'
        padding: dp(8)
        spacing: dp(6)
        BoxLayout:
            size_hint_y: None
            height: dp(48)
            spacing: dp(8)
            Quiet:
                text: 'Kembali'
                size_hint_x: None
                width: dp(100)
                on_release: app.go('home')
            Title:
                text: 'Stock Opname'
        Info:
            id: progress
            text: ''
            color: INK
        Field:
            id: q
            hint_text: 'Cari PLU / deskripsi...'
            on_text: root.reload()
        ScrollView:
            do_scroll_y: False
            bar_width: dp(4)
            BoxLayout:
                orientation: 'vertical'
                size_hint_x: None
                width: dp(W_TABLE)
                SOHeader:
                RecycleView:
                    id: rv
                    viewclass: 'SORow'
                    bar_width: dp(6)
                    RecycleBoxLayout:
                        default_size: None, None
                        default_size_hint: 1, None
                        size_hint_y: None
                        height: self.minimum_height
                        orientation: 'vertical'
                        spacing: dp(1)
        BoxLayout:
            size_hint_y: None
            height: dp(48)
            spacing: dp(6)
            Quiet:
                id: b_rev
                text: 'Revisi'
                disabled: True
                on_release: root.ask_reopen()
            Quiet:
                id: b_wa
                text: 'Kirim WA'
                disabled: True
                on_release: root.share()
            Btn:
                id: b_fin
                text: 'Simpan & Konfirmasi'
                on_release: root.finish()

<FirebaseScreen>:
    name: 'firebase'
    on_pre_enter: root.load()
    BoxLayout:
        orientation: 'vertical'
        padding: dp(12)
        spacing: dp(8)
        BoxLayout:
            size_hint_y: None
            height: dp(48)
            spacing: dp(8)
            Quiet:
                text: 'Kembali'
                size_hint_x: None
                width: dp(100)
                on_release: app.go('home')
            Title:
                text: 'Firebase'
        Info:
            text: 'Opsional. Kosongkan URL untuk memakai aplikasi sepenuhnya lokal (tanpa database).'
        Field:
            id: url
            hint_text: 'URL Realtime Database (https://xxxx.firebaseio.com)'
        Field:
            id: rootpath
            hint_text: 'Path root (default: stockopname)'
        Field:
            id: auth
            hint_text: 'Token / secret (opsional)'
            password: True
        BoxLayout:
            size_hint_y: None
            height: dp(44)
            spacing: dp(8)
            Label:
                text: 'Sinkron otomatis saat menyimpan'
                color: INK
                halign: 'left'
                valign: 'middle'
                text_size: self.size
            Switch:
                id: auto
                size_hint_x: None
                width: dp(80)
        BoxLayout:
            size_hint_y: None
            height: dp(48)
            spacing: dp(8)
            Btn:
                text: 'Simpan'
                on_release: root.save()
            Quiet:
                text: 'Tes koneksi'
                on_release: root.test()
        BoxLayout:
            size_hint_y: None
            height: dp(48)
            spacing: dp(8)
            Quiet:
                text: 'Kirim semua'
                on_release: root.push()
            Quiet:
                text: 'Ambil dari Firebase'
                on_release: root.ask_pull()
        Info:
            id: msg
            text: ''
            color: INK
        Widget:
"""


class StockOpnameApp(App):
    title = "Stock Opname"
    sync_status = ""

    def build(self):
        init_storage(Path(self.user_data_dir) / "data")  # penyimpanan lokal aplikasi
        Window.clearcolor = (0.933, 0.945, 0.965, 1)
        if platform in ("win", "linux", "macosx"):
            Window.size = (480, 800)
        if platform == "android":
            Window.softinput_mode = "below_target"  # papan ketik tidak menutup kolom isian
        Builder.load_string(KV)
        sm = ScreenManager()
        home = HomeScreen()
        for scr in (home, ProductsScreen(), SetupScreen(), SOScreen(), FirebaseScreen()):
            sm.add_widget(scr)
        home.refresh()  # layar pertama: isi status tanpa menunggu on_pre_enter
        Window.bind(on_keyboard=self._on_key)
        return sm

    def go(self, name):
        self.root.current = name

    def pick_product(self, plu):
        self.root.get_screen("products").pick(plu)

    def toggle_setup(self, plu):
        self.root.get_screen("setup").toggle(plu)

    def edit_counts(self, plu, col):
        self.root.get_screen("so").edit(plu, col)

    def _on_key(self, _window, key, *_args):
        """Tombol Kembali Android: tutup popup, lalu kembali ke Beranda, baru keluar."""
        if key != 27:
            return False
        if OPEN_POPUPS:
            OPEN_POPUPS[-1].dismiss()
            return True
        if self.root.current != "home":
            self.root.current = "home"
            return True
        return False

    def on_pause(self):
        return True  # wajib di Android: tanpa ini aplikasi ditutup saat WhatsApp/pemilih terbuka

    def on_resume(self):
        pass


if __name__ == "__main__":
    StockOpnameApp().run()
