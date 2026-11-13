"""
TIMER MAXDIS - logika inti (port Python dari index.html asli).

Setiap fungsi di sini adalah padanan langsung fungsi JavaScript aslinya (nama JS tercantum
di docstring). Rumus, urutan, pembulatan, dan format TIDAK diubah. Kecocokannya dibuktikan
oleh test_main.py terhadap golden.json yang dihasilkan dengan MENJALANKAN kode JavaScript
asli di Node.js (lihat tools/reference.js dan tools/gen_golden.js).
"""
import json
import math
import os
import re
import struct
import time
import wave
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urljoin, urlsplit

LORONG = [("L01", "LORONG 1"), ("L02", "LORONG 2"), ("L03", "LORONG 3"),
          ("L04", "LORONG 4"), ("L05", "LORONG 5"), ("L06", "LORONG 6")]          # lorongData
TIMER_KEY = "timerMaxdisState"
SESSION_KEY = "timerMaxdisSession"
COACH_KEY = "timerMaxdisCoachDone"
SERVER_KEY = "timerMaxdisServerPage"        # tambahan native: alamat halaman TIMER MAXDIS untuk tombol MENU
COACH_STEPS = [("btn_menu", "Tombol MENU digunakan untuk membuka navigasi aplikasi lainnya."),
               ("input_0", "Masukkan QTY barang di sini, lalu tekan ENTER untuk memulai timer.")]
UNDEF = object()                            # padanan `undefined` JavaScript (beda dari null)


# ===================================================== padanan perilaku JavaScript
def js_number(v):
    """Number(v) untuk nilai hasil JSON.parse."""
    if v is UNDEF:
        return math.nan
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return 0.0
        if re.fullmatch(r"0[xX][0-9a-fA-F]+|0[oO][0-7]+|0[bB][01]+", s):
            return float(int(s, 0))
        if s in ("Infinity", "+Infinity"):
            return math.inf
        if s == "-Infinity":
            return -math.inf
        if re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", s):
            return float(s)
        return math.nan
    if isinstance(v, list):
        if not v:
            return 0.0
        if len(v) == 1 and not isinstance(v[0], bool):
            return js_number(v[0])
        return math.nan
    return math.nan


def js_truthy(v):
    if v is None or v is UNDEF or v is False:
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return not (v == 0 or v != v)
    if isinstance(v, str):
        return v != ""
    return True


def is_finite(x):
    return isinstance(x, float) and math.isfinite(x)


def is_integer(x):
    return is_finite(x) and x == math.floor(x)


def js_round(x):
    """Math.round: setengah dibulatkan ke atas (bukan pembulatan bankir Python)."""
    return math.floor(x + 0.5)


def norm_num(x):
    """5.0 -> 5 agar JSON sama dengan JavaScript."""
    if isinstance(x, float) and math.isfinite(x) and x == math.floor(x) and abs(x) < 1e15:
        return int(x)
    return x


def get_field(obj, key):
    return obj.get(key, UNDEF) if isinstance(obj, dict) else UNDEF


def js_to_fixed(x, digits):
    """Number.prototype.toFixed: pembulatan setengah-ke-atas atas nilai biner persis."""
    q = Decimal(abs(x)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return ("-" if x < 0 else "") + format(q, "f")


def format_number_id(x):
    """x.toLocaleString("id-ID"): titik ribuan, koma desimal, maksimal 3 desimal."""
    # Intl membulatkan dari desimal TERPENDEK angkanya (7.1235 -> 7,124), bukan dari nilai biner persis
    q = Decimal(repr(abs(x))).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    whole, _, frac = format(q, "f").partition(".")
    whole = "{:,}".format(int(whole)).replace(",", ".")
    frac = frac.rstrip("0")
    return ("-" if x < 0 else "") + whole + ("," + frac if frac else "")


# ===================================================== UTILITY (formatDuration, formatDateTime, getShift)
def format_duration(total_seconds):
    """formatDuration"""
    n = js_number(total_seconds)
    n = 0 if n != n else n
    total = max(0, js_round(n))
    hours, minutes, seconds = total // 3600, (total % 3600) // 60, total % 60
    if hours > 0:
        return "%02d:%02d:%02d" % (hours, minutes, seconds)
    return "%02d:%02d" % (minutes, seconds)


def format_datetime(timestamp):
    """formatDateTime -> 'dd/MM/yyyy, HH.mm.ss' (id-ID, 24 jam, zona waktu perangkat)"""
    if not js_truthy(timestamp):
        return "-"
    return time.strftime("%d/%m/%Y, %H.%M.%S", time.localtime(math.floor(timestamp / 1000)))


def get_shift(timestamp):
    """getShift"""
    hour = time.localtime(math.floor(timestamp / 1000)).tm_hour
    if 2 <= hour < 6:
        return "SHIFT 3"
    if 9 <= hour < 16:
        return "SHIFT 1"
    if 21 <= hour < 24:
        return "SHIFT 2"
    return "DI LUAR SHIFT"


def now_ms():
    return int(time.time() * 1000)


# ===================================================== CALCULATION
def calculate_total_qty(qty_history):
    total = 0
    for q in qty_history:
        v = js_number(q)
        if is_finite(v) and v > 0:
            total = total + v
    return total


def calculate_work_seconds(records):
    total = 0
    for r in records:
        start, finish = js_number(get_field(r, "start")), js_number(get_field(r, "finish"))
        if finish > start:
            total = total + (finish - start) / 1000
    return total


def calculate_gap_seconds(records):
    gap = 0
    for i in range(1, len(records)):
        gap_ms = js_number(get_field(records[i], "start")) - js_number(get_field(records[i - 1], "finish"))
        if gap_ms > 0:
            gap += gap_ms / 1000
    return gap


def calculate_actual_seconds(records):
    if not records:
        return 0
    first = js_number(get_field(records[0], "start"))
    last = js_number(get_field(records[-1], "finish"))
    if not is_finite(first) or not is_finite(last) or last < first:
        return 0
    return (last - first) / 1000


def calculate_target_seconds(total_qty):
    return (total_qty / 60) * 5 * 60


def evaluate_timing(target_seconds, actual_seconds):
    if target_seconds <= 0:
        return {"deviation": 0, "type": "good", "text": "DATA WAKTU BELUM CUKUP"}
    deviation = ((actual_seconds - target_seconds) / target_seconds) * 100
    if deviation < -10:
        return {"deviation": deviation, "type": "fast", "text": "DISPLAY TERLALU CEPAT"}
    if deviation <= 10:
        return {"deviation": deviation, "type": "good", "text": "BAGUS, DISPLAY TEPAT WAKTU"}
    return {"deviation": deviation, "type": "slow", "text": "DISPLAY TERLALU LAMA"}


def timer_seconds(qty):
    """Math.ceil((qty / 12) * 60)  -- rumus durasi timer, urutan operasi dipertahankan."""
    return math.ceil((qty / 12) * 60)


def tick_info(end_ms, total_seconds, now):
    """Bagian hitung dari updateTimerDisplay()."""
    remaining_ms = max(0, end_ms - now)
    seconds = math.ceil(remaining_ms / 1000)
    minutes, remaining = seconds // 60, seconds % 60
    progress = seconds / total_seconds if total_seconds > 0 else 0
    safe = max(0, min(1, progress))
    if seconds <= 10:
        message = "Hampir selesai!"
    elif seconds <= 30:
        message = "30 detik terakhir."
    elif seconds <= 60:
        message = "Tinggal sebentar lagi."
    else:
        message = "Waktu berjalan."
    return {"display": "%02d:%02d" % (minutes, remaining), "progressPercent": safe * 100,
            "message": message, "finished": remaining_ms <= 0}


def coach_pos(rect, inner_width, inner_height, tip_height):
    """Posisi tooltip tutorial (sama dengan showCoachStep)."""
    width = 260
    left = rect["left"] + rect["width"] / 2 - width / 2
    left = max(10, min(left, inner_width - width - 10))
    top = rect["bottom"] + 15
    if top + tip_height > inner_height - 10:
        top = rect["top"] - tip_height - 15
    return {"left": left, "top": max(10, top)}


# ===================================================== penyimpanan (padanan localStorage)
class MemStorage:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = str(value)

    def remove(self, key):
        self.data.pop(key, None)

    def as_dict(self):
        return dict(self.data)


class FileStorage:
    """Satu berkas per kunci di folder data aplikasi; penulisan atomik."""

    def __init__(self, folder):
        self.folder = str(folder)
        os.makedirs(self.folder, exist_ok=True)

    def _path(self, key):
        return os.path.join(self.folder, re.sub(r"[^A-Za-z0-9_.-]", "_", key) + ".json")

    def get(self, key):
        try:
            with open(self._path(key), "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    def set(self, key, value):
        p = self._path(key)
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            f.write(str(value))
        os.replace(p + ".tmp", p)

    def remove(self, key):
        try:
            os.remove(self._path(key))
        except OSError:
            pass


def dumps(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


# ===================================================== sesi & timer (state JavaScript)
class TimerSession:
    """Seluruh state global JavaScript + fungsi-fungsi yang mengubahnya."""

    def __init__(self, storage, now=now_ms):
        self.storage, self.now = storage, now
        self.current_index = 0
        self.current_qty = 0
        self.current_total_seconds = 0
        self.timer_end_ms = 0
        self.timer_start_ms = 0
        self.is_running = False
        self.qty_history = [None] * len(LORONG)
        self.completed = [False] * len(LORONG)
        self.session_start_ms = 0
        self.records = []

    # ---- TIMER / SESSION STORAGE
    def save_timer_state(self):
        self.storage.set(TIMER_KEY, dumps({"running": True, "index": self.current_index, "qty": norm_num(self.current_qty),
                                           "total": self.current_total_seconds, "end": self.timer_end_ms,
                                           "start": self.timer_start_ms}))

    def clear_timer_state(self):
        self.storage.remove(TIMER_KEY)

    def save_session_state(self):
        self.storage.set(SESSION_KEY, dumps({"index": self.current_index, "qtyHistory": self.qty_history,
                                             "completedLorong": self.completed,
                                             "sessionStartTimestampMs": self.session_start_ms,
                                             "sessionRecords": self.records}))

    def clear_session_state(self):
        self.storage.remove(SESSION_KEY)
        self.qty_history = [None] * len(LORONG)
        self.completed = [False] * len(LORONG)
        self.current_index = 0
        self.current_qty = 0
        self.session_start_ms = 0
        self.records = []

    def load_session_state(self):
        try:
            raw = self.storage.get(SESSION_KEY)
            if not raw:
                return
            state = json.loads(raw)
            if state is None:
                raise TypeError("null")
            if not isinstance(state, dict):
                state = {}
            qh = state.get("qtyHistory", UNDEF)
            if isinstance(qh, list):
                out = []
                for i in range(len(LORONG)):
                    v = js_number(qh[i] if i < len(qh) else UNDEF)
                    out.append(norm_num(v) if (is_finite(v) and v > 0) else None)
                self.qty_history = out
            cl = state.get("completedLorong", UNDEF)
            if isinstance(cl, list):
                self.completed = [(i < len(cl) and cl[i] is True) for i in range(len(LORONG))]
            if is_finite(js_number(state.get("sessionStartTimestampMs", UNDEF))):
                self.session_start_ms = norm_num(js_number(state.get("sessionStartTimestampMs", UNDEF)))
            sr = state.get("sessionRecords", UNDEF)
            if isinstance(sr, list):
                keep = [r for r in sr if js_truthy(r)
                        and all(is_finite(js_number(get_field(r, k))) for k in ("index", "qty", "start", "finish"))]
                self.records = sorted(keep, key=lambda r: js_number(get_field(r, "index")))
            idx = js_number(state.get("index", UNDEF))
            if is_integer(idx) and 0 <= idx < len(LORONG):
                self.current_index = int(idx)
        except Exception:  # noqa: BLE001 - sama dengan catch(error) di JavaScript
            self.clear_session_state()

    # ---- STARTUP RESET (processStartupReset)
    def process_startup_reset(self, navigation_type):
        active = None
        try:
            raw = self.storage.get(TIMER_KEY)
            if raw:
                state = json.loads(raw)
                if js_truthy(state) and isinstance(state, dict) and state.get("running") is True:
                    active = state
        except Exception:  # noqa: BLE001
            active = None
        if navigation_type == "reload" and active:
            self.load_session_state()
            index = js_number(active.get("index", UNDEF))
            if is_integer(index) and 0 <= index < len(LORONG):
                index = int(index)
                self.qty_history[index] = None
                self.completed[index] = False
                self.records = [r for r in self.records if js_number(get_field(r, "index")) != index]
                if index == 0:
                    self.session_start_ms = 0
                    self.records = []
                self.save_session_state()
            self.clear_timer_state()
            return
        self.clear_session_state()
        self.clear_timer_state()

    # ---- START / TICK / FINISH
    def start_timer(self, qty):
        self.is_running = True
        self.current_qty = qty
        self.timer_start_ms = self.now()
        if self.current_index == 0 and len(self.records) == 0:
            self.session_start_ms = self.timer_start_ms
        self.completed[self.current_index] = False
        self.current_total_seconds = timer_seconds(qty)
        self.timer_end_ms = self.timer_start_ms + (self.current_total_seconds * 1000)
        self.save_timer_state()
        self.save_session_state()

    def tick(self):
        return tick_info(self.timer_end_ms, self.current_total_seconds, self.now())

    def finish_timer(self):
        if not self.is_running:
            return False
        self.is_running = False
        self.clear_timer_state()
        self.timer_end_ms = 0
        finish = self.now()
        self.qty_history[self.current_index] = norm_num(self.current_qty)
        self.completed[self.current_index] = True
        self.records.append({"index": self.current_index, "code": LORONG[self.current_index][0],
                             "qty": norm_num(self.current_qty), "start": self.timer_start_ms, "finish": finish})
        self.save_session_state()
        return True

    def ordered_records(self):
        return sorted(self.records, key=lambda r: js_number(get_field(r, "index")))

    def result(self):
        """Bagian hitung/format dari showResultPopup(); None bila lorong belum lengkap."""
        records = self.ordered_records()
        if len(records) != len(LORONG):
            return None
        total_qty = calculate_total_qty(self.qty_history)
        work = calculate_work_seconds(records)
        gap = calculate_gap_seconds(records)
        actual = calculate_actual_seconds(records)
        target = calculate_target_seconds(total_qty)
        ev = evaluate_timing(target, actual)
        first_start = js_number(records[0]["start"])
        last_finish = js_number(records[-1]["finish"])
        dev = ev["deviation"]
        return {"totalQty": format_number_id(total_qty), "shift": get_shift(first_start),
                "target": format_duration(target), "work": format_duration(work), "gap": format_duration(gap),
                "actual": format_duration(actual),
                "percent": ("+" if dev >= 0 else "") + js_to_fixed(dev, 1) + "%",
                "finishedAt": format_datetime(last_finish), "statusType": ev["type"], "statusText": ev["text"]}

    def finish_lorong(self):
        """Bagian logika finishLorong(): (selesai_semua, hasil)."""
        self.clear_timer_state()
        self.current_index += 1
        if self.current_index >= len(LORONG):
            self.save_session_state()
            return True, self.result()
        self.save_session_state()
        return False, None

    def reset_completed_session(self):
        self.clear_session_state()
        self.clear_timer_state()

    def snapshot(self):
        return {"currentIndex": self.current_index, "qtyHistory": self.qty_history, "completedLorong": self.completed,
                "sessionStartTimestampMs": self.session_start_ms, "sessionRecords": self.records,
                "storage": self.storage.as_dict() if hasattr(self.storage, "as_dict") else {}}


# ===================================================== alarm: beep() = gelombang kotak 900 Hz, 500 ms
def make_beep_wav(path, frequency=900, duration_ms=500, rate=22050):
    """Sama dengan beep(): oscillator 'square', gain 0 -> .9 dalam 20 ms -> 0 di akhir (linear)."""
    n = int(rate * duration_ms / 1000)
    dur = duration_ms / 1000
    frames = bytearray()
    for i in range(n):
        t = i / rate
        env = 0.9 * (t / 0.02) if t < 0.02 else 0.9 * max(0.0, (dur - t) / (dur - 0.02))
        wave_v = 1.0 if math.sin(2 * math.pi * frequency * t) >= 0 else -1.0
        frames += struct.pack("<h", int(wave_v * env * 32767 * 0.8))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return str(path)


# ===================================================== tombol MENU -> ./menu.html di server
def normalize_page_url(text):
    t = (text or "").strip()
    if not t:
        raise ValueError("Alamat belum diisi")
    if "://" not in t:
        t = "https://" + t
    p = urlsplit(t)
    if p.scheme not in ("http", "https") or not p.netloc or " " in t:
        raise ValueError("Alamat tidak valid")
    return t


def menu_url(page_url):
    """href='./menu.html' diselesaikan terhadap alamat halaman, persis seperti browser."""
    return urljoin(page_url, "./menu.html")
