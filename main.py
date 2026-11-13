"""
TIMER MAXDIS (Kivy)

  logic.py : port logika inti dari JavaScript asli (dibuktikan sama persis lewat golden.json)
  main.py  : Controller (alur aplikasi, tanpa widget -> bisa diuji) + antarmuka Kivy

Instalasi : pip install kivy
Pengujian : pip install pytest pyyaml && pytest -v test_main.py
Android   : lihat README.md
"""
import json
import math
import os
import webbrowser

from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput
from kivy.utils import platform

import logic

SPLASH_SHOW_S, SPLASH_FADE_S = 0.7, 0.4          # initApp(): 700 ms lalu 400 ms
FOCUS_DELAY_S = 0.15                              # setTimeout(focusCurrentInput, 150)
TICK_S, ALARM_S = 0.2, 1.0                        # setInterval(updateTimerDisplay, 200) dan alarm 1000 ms
LONG_PRESS_S = 0.8
TOOLTIP_H = 120                                   # tinggi tooltip tutorial (dp)


def parse_qty_text(text):
    """Number(event.target.value) pada <input type=number>; koma desimal diterima seperti di browser."""
    return logic.js_number((text or "").strip().replace(",", "."))


def qty_str(x):
    """Penulisan angka seperti `${qty}` di JavaScript."""
    x = logic.norm_num(float(x))
    return str(x)


# ============================================================ layanan platform (dapat diganti saat uji)
class Services:
    def __init__(self, data_dir):
        self.data_dir = str(data_dir)
        self._sound = None

    def now(self):
        return logic.now_ms()

    def every(self, seconds, fn):
        return Clock.schedule_interval(lambda _dt: fn(), seconds)

    def later(self, seconds, fn):
        return Clock.schedule_once(lambda _dt: fn(), seconds)

    def cancel(self, ev):
        if ev is not None:
            ev.cancel()

    def beep(self):
        """beep(900, 500): gelombang kotak 900 Hz selama 500 ms."""
        try:
            if self._sound is None:
                path = os.path.join(self.data_dir, "beep.wav")
                if not os.path.exists(path):
                    logic.make_beep_wav(path)
                from kivy.core.audio import SoundLoader
                self._sound = SoundLoader.load(path)
            if self._sound:
                self._sound.stop()
                self._sound.play()
        except Exception:  # noqa: BLE001 - alarm tidak boleh menjatuhkan aplikasi
            pass

    def keep_screen_on(self, on):
        """requestWakeLock()/releaseWakeLock(): layar tetap menyala selama timer berjalan (Android)."""
        if platform != "android":
            return False
        try:
            from android.runnable import run_on_ui_thread
            from jnius import autoclass

            @run_on_ui_thread
            def apply():
                activity = autoclass("org.kivy.android.PythonActivity").mActivity
                flag = autoclass("android.view.WindowManager$LayoutParams").FLAG_KEEP_SCREEN_ON
                window = activity.getWindow()
                (window.addFlags if on else window.clearFlags)(flag)
            apply()
            return True
        except Exception:  # noqa: BLE001
            return False

    def open_url(self, url):
        """Buka alamat di browser (padanan window.location.href = './menu.html')."""
        if platform == "android":
            from jnius import autoclass
            intent_cls, uri_cls = autoclass("android.content.Intent"), autoclass("android.net.Uri")
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            activity.startActivity(intent_cls(intent_cls.ACTION_VIEW, uri_cls.parse(url)))
        else:
            webbrowser.open(url)


# ============================================================ alur aplikasi (tanpa widget)
class Controller:
    """Padanan fungsi-fungsi JavaScript yang menghubungkan state, timer, dan tampilan."""

    def __init__(self, ui, storage, svc):
        self.ui, self.storage, self.svc = ui, storage, svc
        self.session = logic.TimerSession(storage, svc.now)
        self.tick_ev = self.alarm_ev = None
        self.coach_step = 0
        self.timer_visible = self.result_visible = self.coach_visible = False

    # ---- initApp()
    def _has_active_timer(self):
        try:
            raw = self.storage.get(logic.TIMER_KEY)
            state = json.loads(raw) if raw else None
            return isinstance(state, dict) and state.get("running") is True
        except Exception:  # noqa: BLE001
            return False

    def init_app(self):
        # Dibuka ulang saat timer masih berjalan (proses ditutup paksa) = "reload"; selain itu = "navigate".
        self.session.process_startup_reset("reload" if self._has_active_timer() else "navigate")
        self.render()
        self.ui.show_splash()
        self.svc.later(SPLASH_SHOW_S, self._splash_fade)

    def _splash_fade(self):
        self.ui.fade_splash()
        self.svc.later(SPLASH_FADE_S, self._splash_done)

    def _splash_done(self):
        self.ui.hide_splash()
        self.start_coach()

    # ---- renderList()
    def render(self):
        s = self.session
        self.ui.render_list(s.current_index, s.qty_history, s.completed)
        self.ui.set_stepper(2 if s.is_running else 1)

    def focus(self):
        self.ui.focus_input(self.session.current_index)

    # ---- handleInputKey() -> startTimer()
    def on_enter(self, index, text):
        s = self.session
        if index != s.current_index:
            return False
        qty = parse_qty_text(text)
        if not (math.isfinite(qty) and qty > 0):
            self.ui.alert("Masukkan Qty lebih dari 0.")
            return False
        if s.is_running:
            return False
        self.start(logic.norm_num(qty))
        return True

    def start(self, qty):
        s = self.session
        s.start_timer(qty)
        self.timer_visible = True
        self.ui.show_timer(logic.LORONG[s.current_index][1], "QTY " + qty_str(qty))
        self.tick()
        self.svc.keep_screen_on(True)
        self.svc.cancel(self.tick_ev)
        self.tick_ev = self.svc.every(TICK_S, self.tick)

    # ---- updateTimerDisplay()
    def tick(self):
        s = self.session
        if not s.is_running:
            return
        info = s.tick()
        self.ui.update_timer(info["display"], info["progressPercent"], info["message"])
        if info["finished"]:
            self.finish_timer()

    # ---- finishTimer()
    def finish_timer(self):
        if not self.session.finish_timer():
            return
        self.svc.cancel(self.tick_ev)
        self.tick_ev = None
        self.svc.keep_screen_on(False)
        self.ui.show_timer_finished()
        self.ui.set_stepper(3)
        self.start_alarm()

    def start_alarm(self):
        self.stop_alarm()
        self.svc.beep()
        self.alarm_ev = self.svc.every(ALARM_S, self.svc.beep)

    def stop_alarm(self):
        self.svc.cancel(self.alarm_ev)
        self.alarm_ev = None

    # ---- finishLorong()
    def next_lorong(self):
        self.stop_alarm()
        self.session.clear_timer_state()
        self.svc.keep_screen_on(False)
        self.ui.hide_timer()
        self.timer_visible = False
        done, result = self.session.finish_lorong()
        if done:
            if result is not None:                      # showResultPopup() diam bila lorong belum lengkap
                self.result_visible = True
                self.ui.show_result(result)
            return
        self.render()
        self.svc.later(FOCUS_DELAY_S, self.focus)

    # ---- resetCompletedSession()
    def result_ok(self):
        self.session.reset_completed_session()
        self.result_visible = False
        self.ui.hide_result()
        self.render()
        self.svc.later(FOCUS_DELAY_S, self.focus)

    # ---- tombol MENU: clearTimerState(); window.location.href = './menu.html'
    def menu(self):
        self.session.clear_timer_state()
        page = self.storage.get(logic.SERVER_KEY)
        if page:
            self._open_menu(page)
        else:
            self.ui.ask_server_url("", self.save_server_and_open)

    def edit_server(self):
        self.ui.ask_server_url(self.storage.get(logic.SERVER_KEY) or "", self.save_server_and_open)

    def save_server_and_open(self, text):
        try:
            page = logic.normalize_page_url(text)
        except ValueError as e:
            self.ui.alert(str(e) + ". Contoh: https://domain-anda.com/timer/")
            return False
        self.storage.set(logic.SERVER_KEY, page)
        self._open_menu(page)
        return True

    def _open_menu(self, page):
        try:
            self.svc.open_url(logic.menu_url(page))
        except Exception as e:  # noqa: BLE001
            self.ui.alert("Tidak dapat membuka browser: %s" % e)

    # ---- tutorial (coach)
    def start_coach(self):
        if self.storage.get(logic.COACH_KEY) == "true":
            self.focus()
            return
        self.coach_step = 0
        self.show_coach_step()

    def show_coach_step(self):
        if self.coach_step >= len(logic.COACH_STEPS):
            self.coach_visible = False
            self.ui.hide_coach()
            self.storage.set(logic.COACH_KEY, "true")
            self.focus()
            return
        name, text = logic.COACH_STEPS[self.coach_step]
        rect = self.ui.coach_target_rect(name)
        if rect is None:
            self.coach_step += 1
            return self.show_coach_step()
        self.coach_visible = True
        self.ui.show_coach(rect, text, self.coach_step == len(logic.COACH_STEPS) - 1)

    def next_coach(self):
        self.coach_step += 1
        self.show_coach_step()

    # ---- siklus hidup (visibilitychange / pageshow)
    def on_resume(self):
        if self.session.is_running:
            self.tick()
            self.svc.keep_screen_on(True)

    def on_back(self):
        """Tombol Kembali Android: diabaikan saat timer/hasil/tutorial tampil (hindari keluar tak sengaja)."""
        return bool(self.timer_visible or self.result_visible or self.coach_visible)


# ============================================================ widget
class MenuButton(Button):
    """MENU: ketuk = buka menu; tekan lama = ubah alamat server."""
    long_fired = False
    _ev = None

    def on_touch_down(self, touch):
        hit = super().on_touch_down(touch)
        if hit:
            self.long_fired = False
            self._ev = Clock.schedule_once(self._fire_long, LONG_PRESS_S)
        return hit

    def _fire_long(self, _dt):
        self.long_fired = True
        App.get_running_app().controller.edit_server()

    def on_touch_up(self, touch):
        if self._ev is not None:
            self._ev.cancel()
            self._ev = None
        return super().on_touch_up(touch)


class LorongRow(BoxLayout):
    index = NumericProperty(0)
    code = StringProperty("")
    name = StringProperty("")
    qty_text = StringProperty("")
    active = BooleanProperty(False)
    done = BooleanProperty(False)

    def qty_filter(self, substring, _from_undo):
        return "".join(c for c in substring if c in "0123456789.,")

    def submit(self):
        App.get_running_app().controller.on_enter(self.index, self.ids.field.text)


class TimerOverlay(FloatLayout):
    alarm = BooleanProperty(False)
    flash = BooleanProperty(False)
    finished = BooleanProperty(False)
    title_text = StringProperty("LORONG X")
    qty_text = StringProperty("QTY 0")
    time_text = StringProperty("00:00")
    message = StringProperty("Waktu berjalan.")
    progress = NumericProperty(100.0)

    def on_touch_down(self, touch):
        super().on_touch_down(touch)
        return True                                     # menutupi layar: sentuhan tidak tembus ke daftar


class ResultView(ModalView):
    pass


class CoachOverlay(FloatLayout):
    hx = NumericProperty(0)
    hy = NumericProperty(0)
    hw = NumericProperty(0)
    hh = NumericProperty(0)
    tx = NumericProperty(0)
    ty = NumericProperty(0)
    text = StringProperty("")
    next_text = StringProperty("Lanjut")

    def on_touch_down(self, touch):
        super().on_touch_down(touch)
        return True


class SplashView(FloatLayout):
    angle = NumericProperty(0)

    def on_touch_down(self, touch):
        return True


class RootView(FloatLayout):
    """Seluruh layar utama + antarmuka yang dipanggil Controller."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.rows, self.timer, self.splash, self.coach, self.result = [], None, None, None, None
        self._spin = self._flash_ev = self._belt_ev = self._pulse = None

    # ---- daftar lorong & stepper
    def render_list(self, index, qty_history, completed):
        box = self.ids.rows
        box.clear_widgets()
        self.rows = []
        for i, (code, name) in enumerate(logic.LORONG):
            row = LorongRow()
            row.index, row.code, row.name = i, code, name
            row.qty_text = "" if qty_history[i] is None else qty_str(qty_history[i])
            row.active, row.done = (i == index), bool(completed[i])
            box.add_widget(row)
            self.rows.append(row)

    def set_stepper(self, step):
        a, b, c = {1: ("active", "", ""), 2: ("done", "active", ""), 3: ("done", "done", "active")}[step]
        self.ids.s1.state, self.ids.s2.state, self.ids.s3.state = a, b, c

    def focus_input(self, index):
        if 0 <= index < len(self.rows):
            field = self.rows[index].ids.field
            field.focus = True
            try:
                field.select_all()
            except Exception:  # noqa: BLE001
                pass

    def alert(self, text):
        box = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(14))
        lbl = Label(text=text, color=(0.2, 0.2, 0.2, 1), halign="center")
        lbl.bind(width=lambda w, x: setattr(w, "text_size", (x, None)))
        btn = Button(text="OK", size_hint_y=None, height=dp(44), bold=True, background_normal="",
                     background_color=(0.898, 0.106, 0.137, 1))
        box.add_widget(lbl)
        box.add_widget(btn)
        pop = Popup(title="TIMER MAXDIS", content=box, size_hint=(0.86, None), height=dp(210),
                    background="", background_color=(1, 1, 1, 1), title_color=(0.2, 0.2, 0.2, 1),
                    separator_color=(0.898, 0.106, 0.137, 1))
        btn.bind(on_release=lambda *_: pop.dismiss())
        pop.open()

    # ---- splash
    def show_splash(self):
        self.splash = SplashView()
        self.add_widget(self.splash)
        self._spin = Clock.schedule_interval(lambda dt: setattr(self.splash, "angle", (self.splash.angle + 7) % 360), 1 / 30)

    def fade_splash(self):
        Animation(opacity=0, duration=SPLASH_FADE_S).start(self.splash)

    def hide_splash(self):
        if self._spin:
            self._spin.cancel()
        if self.splash:
            self.remove_widget(self.splash)
            self.splash = None

    # ---- overlay timer
    def show_timer(self, title, qty_text):
        t = self.timer = TimerOverlay()
        t.title_text, t.qty_text = title, qty_text
        t.alarm = t.flash = t.finished = False
        t.progress, t.message = 100.0, "Waktu berjalan."
        self.add_widget(t)
        self._pulse = Animation(opacity=0.45, duration=0.6) + Animation(opacity=1, duration=0.6)
        self._pulse.repeat = True
        self._pulse.start(t.ids.dot)
        self._belt_ev = Clock.schedule_interval(lambda dt: setattr(t.ids.belt, "phase", (t.ids.belt.phase + dt * 0.35) % 1), 1 / 30)

    def update_timer(self, display, progress_percent, message):
        t = self.timer
        t.time_text, t.progress, t.message = display, progress_percent, message

    def show_timer_finished(self):
        t = self.timer
        t.time_text, t.progress, t.message = "00:00", 100.0, "WAKTU HABIS!"
        t.alarm, t.finished = True, True
        if self._belt_ev:
            self._belt_ev.cancel()
        self._flash_ev = Clock.schedule_interval(lambda dt: setattr(t, "flash", not t.flash), 0.5)   # flashRed 1s

    def hide_timer(self):
        for ev in (self._flash_ev, self._belt_ev):
            if ev:
                ev.cancel()
        if self.timer:
            Animation.cancel_all(self.timer.ids.dot)
            self.remove_widget(self.timer)
            self.timer = None

    # ---- popup hasil
    def show_result(self, r):
        v = self.result = ResultView()
        ids = v.ids
        ids.status.text, ids.status.kind = r["statusText"], r["statusType"]
        for key, value in (("qty", r["totalQty"]), ("shift", r["shift"]), ("target", r["target"]), ("work", r["work"]),
                           ("gap", r["gap"]), ("actual", r["actual"]), ("percent", r["percent"]), ("finished", r["finishedAt"])):
            ids[key].value = value
        v.open()

    def hide_result(self):
        if self.result:
            self.result.dismiss()
            self.result = None

    # ---- tutorial
    def coach_target_rect(self, name):
        target = self.ids.btn_menu if name == "btn_menu" else (self.rows[0].ids.field if self.rows else None)
        if target is None or target.parent is None:
            return None
        x, y = target.to_window(target.x, target.y)
        u, win_h = dp(1), Window.height
        return {"left": x / u, "top": (win_h - (y + target.height)) / u, "bottom": (win_h - y) / u,
                "width": target.width / u, "height": target.height / u, "_x": x, "_y": y, "_w": target.width, "_h": target.height}

    def show_coach(self, rect, text, last):
        if self.coach is None:
            self.coach = CoachOverlay()
            self.add_widget(self.coach)
        u, c = dp(1), self.coach
        pos = logic.coach_pos(rect, Window.width / u, Window.height / u, TOOLTIP_H)
        c.hx, c.hy, c.hw, c.hh = rect["_x"] - u * 3, rect["_y"] - u * 3, rect["_w"] + u * 6, rect["_h"] + u * 6
        c.tx, c.ty = pos["left"] * u, Window.height - (pos["top"] + TOOLTIP_H) * u
        c.text, c.next_text = text, ("Mulai Kerja!" if last else "Lanjut")

    def hide_coach(self):
        if self.coach:
            self.remove_widget(self.coach)
            self.coach = None

    # ---- alamat server untuk tombol MENU
    def ask_server_url(self, current, on_ok):
        box = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(10))
        box.add_widget(Label(text="Alamat halaman TIMER MAXDIS di server Anda\n(persis seperti di browser).\nTombol MENU akan membuka menu.html dari alamat ini.",
                             color=(0.2, 0.2, 0.2, 1), halign="center", font_size=dp(13)))
        field = TextInput(text=current, hint_text="https://apktoko.arinex.my.id/menu.html/", multiline=False, size_hint_y=None, height=dp(44),
                          write_tab=False, input_type="url")
        box.add_widget(field)
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        pop = Popup(title="Alamat server", content=box, size_hint=(0.92, None), height=dp(330), auto_dismiss=False,
                    background="", background_color=(1, 1, 1, 1), title_color=(0.2, 0.2, 0.2, 1), separator_color=(0.898, 0.106, 0.137, 1))
        cancel = Button(text="Batal", background_normal="", background_color=(0.9, 0.92, 0.95, 1), color=(0.2, 0.2, 0.2, 1))
        save = Button(text="Simpan & Buka", bold=True, background_normal="", background_color=(0.898, 0.106, 0.137, 1))
        cancel.bind(on_release=lambda *_: pop.dismiss())
        save.bind(on_release=lambda *_: (pop.dismiss() if on_ok(field.text) else None))
        row.add_widget(cancel)
        row.add_widget(save)
        box.add_widget(row)
        pop.open()


KV = """
#:import dp kivy.metrics.dp
#:import sp kivy.metrics.sp
#:set RED (0.898, 0.106, 0.137, 1)
#:set BLUE (0, 0.369, 0.667, 1)
#:set GREEN (0.298, 0.686, 0.314, 1)
#:set INK (0.2, 0.2, 0.2, 1)

<Panel@BoxLayout>:
    bg: 1, 1, 1, 1
    border: 0.89, 0.91, 0.94, 1
    rad: dp(12)
    canvas.before:
        Color:
            rgba: self.bg
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [self.rad]
        Color:
            rgba: self.border
        Line:
            rounded_rectangle: self.x, self.y, self.width, self.height, self.rad
            width: 1

<RedBtn@Button>:
    background_normal: ''
    background_down: ''
    background_color: RED
    color: 1, 1, 1, 1
    bold: True

<CheckMark@Widget>:
    mark: 1, 1, 1, 1
    canvas:
        Color:
            rgba: self.mark
        Line:
            points: self.x + self.width * 0.26, self.y + self.height * 0.52, self.x + self.width * 0.43, self.y + self.height * 0.32, self.x + self.width * 0.76, self.y + self.height * 0.70
            width: dp(2)
            cap: 'round'
            joint: 'round'

<StatusIcon@FloatLayout>:
    done: False
    size_hint: None, None
    size: dp(24), dp(24)
    canvas.before:
        Color:
            rgba: GREEN if self.done else (0.933, 0.933, 0.933, 1)
        Ellipse:
            pos: self.pos
            size: self.size
    CheckMark:
        opacity: 1 if root.done else 0

<StepItem@BoxLayout>:
    num: '1'
    caption: ''
    state: ''
    orientation: 'vertical'
    size_hint_x: None
    width: dp(80)
    spacing: dp(5)
    FloatLayout:
        size_hint: None, None
        size: dp(35), dp(35)
        pos_hint: {'center_x': .5}
        canvas.before:
            Color:
                rgba: GREEN if root.state == 'done' else (BLUE if root.state == 'active' else (0.878, 0.878, 0.878, 1))
            Ellipse:
                pos: self.pos
                size: self.size
        Label:
            text: root.num
            bold: True
            color: 1, 1, 1, 1
    Label:
        text: root.caption
        font_size: sp(12)
        bold: root.state == 'active'
        color: BLUE if root.state == 'active' else (0.6, 0.6, 0.6, 1)
        size_hint_y: None
        height: dp(18)

<Ring@Widget>:
    progress: 100.0
    alarm: False
    canvas:
        Color:
            rgba: (1, 1, 1, 0.2) if self.alarm else (0.898, 0.906, 0.922, 1)
        Ellipse:
            pos: self.pos
            size: self.size
        Color:
            rgba: (1, 1, 1, 1) if self.alarm else RED
        Ellipse:
            pos: self.pos
            size: self.size
            angle_start: 270
            angle_end: 270 + self.progress * 3.6
        Color:
            rgba: RED if self.alarm else (1, 1, 1, 1)
        Ellipse:
            pos: self.x + dp(11), self.y + dp(11)
            size: self.width - dp(22), self.height - dp(22)

<ConveyorAnim@Widget>:
    phase: 0.0
    canvas:
        Color:
            rgba: 0.82, 0.84, 0.87, 1
        Rectangle:
            pos: self.x + dp(12), self.y + dp(34)
            size: self.width - dp(24), dp(6)
        Color:
            rgba: BLUE
        RoundedRectangle:
            pos: self.x + dp(10) + ((self.phase + 0.00) % 1) * (self.width - dp(84)), self.y + dp(40)
            size: dp(50), dp(40)
            radius: [dp(6)]
        Color:
            rgba: RED
        RoundedRectangle:
            pos: self.x + dp(10) + ((self.phase + 0.25) % 1) * (self.width - dp(84)), self.y + dp(40)
            size: dp(50), dp(40)
            radius: [dp(6)]
        Color:
            rgba: BLUE
        RoundedRectangle:
            pos: self.x + dp(10) + ((self.phase + 0.50) % 1) * (self.width - dp(84)), self.y + dp(40)
            size: dp(50), dp(40)
            radius: [dp(6)]
        Color:
            rgba: RED
        RoundedRectangle:
            pos: self.x + dp(10) + ((self.phase + 0.75) % 1) * (self.width - dp(84)), self.y + dp(40)
            size: dp(50), dp(40)
            radius: [dp(6)]

<PulseDot@Widget>:
    size_hint: None, None
    size: dp(9), dp(9)
    canvas:
        Color:
            rgba: GREEN
        Ellipse:
            pos: self.pos
            size: self.size

<ResultCard@BoxLayout>:
    caption: ''
    value: ''
    orientation: 'vertical'
    padding: dp(11)
    spacing: dp(4)
    size_hint_y: None
    height: dp(70)
    canvas.before:
        Color:
            rgba: 0.973, 0.98, 0.988, 1
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(13)]
        Color:
            rgba: 0.89, 0.91, 0.94, 1
        Line:
            rounded_rectangle: self.x, self.y, self.width, self.height, dp(13)
            width: 1
    Label:
        text: root.caption.upper()
        font_size: sp(11)
        bold: True
        color: 0.58, 0.64, 0.72, 1
        halign: 'left'
        valign: 'middle'
        text_size: self.size
    Label:
        text: root.value
        font_size: sp(17)
        bold: True
        color: 0.12, 0.16, 0.22, 1
        halign: 'left'
        valign: 'middle'
        text_size: self.size

<LorongRow>:
    orientation: 'horizontal'
    size_hint_y: None
    height: dp(66)
    padding: dp(15), dp(8)
    spacing: dp(8)
    canvas.before:
        Color:
            rgba: (0.89, 0.949, 0.992, 1) if self.active else (1, 1, 1, 1)
        Rectangle:
            pos: self.pos
            size: self.size
        Color:
            rgba: BLUE if self.active else (0, 0, 0, 0)
        Rectangle:
            pos: self.pos
            size: dp(4), self.height
        Color:
            rgba: 0.933, 0.933, 0.933, 1
        Rectangle:
            pos: self.x, self.y
            size: self.width, 1
    BoxLayout:
        orientation: 'vertical'
        spacing: dp(2)
        Label:
            text: root.code
            font_size: sp(12)
            color: 0.53, 0.53, 0.53, 1
            halign: 'left'
            valign: 'bottom'
            text_size: self.size
        Label:
            text: root.name
            font_size: sp(14)
            bold: True
            color: INK
            halign: 'left'
            valign: 'top'
            text_size: self.size
    TextInput:
        id: field
        size_hint: None, None
        size: dp(64), dp(40)
        pos_hint: {'center_y': .5}
        multiline: False
        write_tab: False
        input_type: 'number'
        input_filter: root.qty_filter
        halign: 'center'
        font_size: sp(15)
        hint_text: '0'
        text: root.qty_text
        disabled: not root.active
        padding: dp(8), dp(10)
        background_normal: ''
        background_active: ''
        background_disabled_normal: ''
        background_color: (1, 1, 1, 1) if root.active else (0.969, 0.969, 0.969, 1)
        foreground_color: INK
        disabled_foreground_color: 0.467, 0.467, 0.467, 1
        on_text_validate: root.submit()
    StatusIcon:
        pos_hint: {'center_y': .5}
        done: root.done

<TimerOverlay>:
    canvas.before:
        Color:
            rgba: ((1, 0.322, 0.322, 1) if self.flash else RED) if self.alarm else (0.973, 0.98, 0.988, 1)
        Rectangle:
            pos: self.pos
            size: self.size
    BoxLayout:
        orientation: 'vertical'
        size_hint: None, None
        width: min(root.width - dp(36), dp(470))
        height: root.height - dp(36)
        pos_hint: {'center_x': .5, 'center_y': .5}
        spacing: dp(8)
        Widget:
        BoxLayout:
            size_hint_y: None
            height: dp(34)
            Panel:
                bg: (1, 1, 1, 0.16) if root.alarm else (0.89, 0.949, 0.992, 1)
                border: 0, 0, 0, 0
                rad: dp(17)
                size_hint: None, 1
                width: dp(150)
                padding: dp(14), 0
                spacing: dp(7)
                PulseDot:
                    id: dot
                    pos_hint: {'center_y': .5}
                Label:
                    text: 'TIMER AKTIF'
                    font_size: sp(12)
                    bold: True
                    color: (1, 1, 1, 1) if root.alarm else BLUE
                    halign: 'left'
                    valign: 'middle'
                    text_size: self.size
            Widget:
            Panel:
                bg: (1, 1, 1, 0.16) if root.alarm else (1, 1, 1, 1)
                rad: dp(17)
                size_hint: None, 1
                width: dp(110)
                Label:
                    text: root.qty_text
                    font_size: sp(12)
                    bold: True
                    color: (1, 1, 1, 1) if root.alarm else (0.33, 0.33, 0.33, 1)
        Label:
            text: root.title_text
            font_size: sp(26)
            bold: True
            color: (1, 1, 1, 1) if root.alarm else (0.12, 0.16, 0.22, 1)
            size_hint_y: None
            height: dp(40)
        Label:
            text: 'Sedang mengerjakan...'
            font_size: sp(14)
            color: (1, 1, 1, 1) if root.alarm else (0.42, 0.45, 0.5, 1)
            size_hint_y: None
            height: dp(22)
        Panel:
            bg: 0.957, 0.965, 0.973, 1
            rad: dp(18)
            size_hint: None, None
            size: min(root.width * 0.92, dp(380)), (dp(155) if not root.finished else dp(0.01))
            pos_hint: {'center_x': .5}
            opacity: 0 if root.finished else 1
            ConveyorAnim:
                id: belt
        FloatLayout:
            size_hint: None, None
            size: min(root.width * 0.72, dp(300)), min(root.width * 0.72, dp(300))
            pos_hint: {'center_x': .5}
            Ring:
                progress: root.progress
                alarm: root.alarm
            BoxLayout:
                orientation: 'vertical'
                Widget:
                Label:
                    text: root.time_text
                    font_name: 'data/fonts/RobotoMono-Regular.ttf'
                    font_size: min(max(dp(58), root.width * 0.16), dp(96))
                    bold: True
                    color: (1, 1, 1, 1) if root.alarm else (0.133, 0.133, 0.133, 1)
                    size_hint_y: None
                    height: dp(80)
                Label:
                    text: 'WAKTU TERSISA'
                    font_size: sp(12)
                    bold: True
                    color: (1, 1, 1, 0.8) if root.alarm else (0.61, 0.64, 0.69, 1)
                    size_hint_y: None
                    height: dp(22)
                Widget:
        Panel:
            bg: (1, 1, 1, 0.14) if root.alarm else (1, 1, 1, 0.9)
            border: 0, 0, 0, 0
            rad: dp(14)
            size_hint: None, None
            size: min(root.width * 0.92, dp(430)), dp(52)
            pos_hint: {'center_x': .5}
            padding: dp(12), dp(6)
            Label:
                text: root.message
                font_size: sp(15)
                bold: True
                color: (1, 1, 1, 1) if root.alarm else (0.29, 0.33, 0.39, 1)
                halign: 'center'
                valign: 'middle'
                text_size: self.size
        RedBtn:
            text: 'LANJUT LORONG BERIKUTNYA'
            font_size: sp(15)
            size_hint: None, None
            size: dp(300), dp(50)
            pos_hint: {'center_x': .5}
            opacity: 1 if root.finished else 0
            disabled: not root.finished
            on_release: app.controller.next_lorong()
        Widget:

<StatusBox@BoxLayout>:
    kind: 'good'
    text: ''
    canvas.before:
        Color:
            rgba: (0.91, 0.961, 0.914, 1) if self.kind == 'good' else ((1, 0.973, 0.882, 1) if self.kind == 'fast' else (1, 0.922, 0.933, 1))
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(14)]
    Label:
        text: root.text
        font_size: sp(16)
        bold: True
        color: (0.18, 0.49, 0.2, 1) if root.kind == 'good' else ((0.937, 0.424, 0, 1) if root.kind == 'fast' else (0.776, 0.157, 0.157, 1))

<ResultView>:
    auto_dismiss: False
    size_hint: 0.92, 0.9
    background: ''
    background_color: 1, 1, 1, 1
    overlay_color: 0.06, 0.09, 0.16, 0.76
    ScrollView:
        do_scroll_x: False
        BoxLayout:
            orientation: 'vertical'
            size_hint_y: None
            height: self.minimum_height
            padding: dp(20)
            spacing: dp(12)
            FloatLayout:
                size_hint: None, None
                size: dp(66), dp(66)
                pos_hint: {'center_x': .5}
                canvas.before:
                    Color:
                        rgba: 0.89, 0.949, 0.992, 1
                    Ellipse:
                        pos: self.pos
                        size: self.size
                CheckMark:
                    mark: BLUE
            Label:
                text: 'SELURUH LORONG SELESAI'
                font_size: sp(20)
                bold: True
                color: RED
                size_hint_y: None
                height: dp(30)
            Label:
                text: 'Seluruh lorong sudah dikerjakan. Berikut hasil pengerjaan pada sesi ini.'
                font_size: sp(14)
                color: 0.39, 0.45, 0.55, 1
                halign: 'center'
                text_size: self.width, None
                size_hint_y: None
                height: self.texture_size[1] + dp(6)
            StatusBox:
                id: status
                size_hint_y: None
                height: dp(52)
            GridLayout:
                cols: 2
                spacing: dp(10)
                size_hint_y: None
                height: self.minimum_height
                ResultCard:
                    id: qty
                    caption: 'Total Qty'
                ResultCard:
                    id: shift
                    caption: 'Shift'
                ResultCard:
                    id: target
                    caption: 'Waktu Standar'
                ResultCard:
                    id: work
                    caption: 'Waktu Kerja'
                ResultCard:
                    id: gap
                    caption: 'Total Gap'
                ResultCard:
                    id: actual
                    caption: 'Waktu Aktual'
            ResultCard:
                id: percent
                caption: 'Deviasi'
            ResultCard:
                id: finished
                caption: 'Waktu Selesai'
            Label:
                text: 'Waktu aktual dihitung dari mulai Lorong 1 sampai Lorong terakhir selesai. Gap antar-lorong ikut dihitung. Rentang -10% sampai +10% dianggap tepat waktu.'
                font_size: sp(12)
                color: 0.28, 0.33, 0.41, 1
                halign: 'center'
                text_size: self.width, None
                size_hint_y: None
                height: self.texture_size[1] + dp(16)
            RedBtn:
                text: 'OK'
                font_size: sp(16)
                size_hint_y: None
                height: dp(48)
                on_release: app.controller.result_ok()

<CoachOverlay>:
    canvas.before:
        Color:
            rgba: 0, 0, 0, 0.7
        Rectangle:
            pos: 0, 0
            size: self.width, root.hy
        Rectangle:
            pos: 0, root.hy + root.hh
            size: self.width, max(0, self.height - root.hy - root.hh)
        Rectangle:
            pos: 0, root.hy
            size: root.hx, root.hh
        Rectangle:
            pos: root.hx + root.hw, root.hy
            size: max(0, self.width - root.hx - root.hw), root.hh
        Color:
            rgba: 0.98, 0.82, 0.08, 1
        Line:
            rectangle: root.hx, root.hy, root.hw, root.hh
            width: dp(3)
    Panel:
        orientation: 'vertical'
        size_hint: None, None
        size: dp(260), dp(120)
        x: root.tx
        y: root.ty
        rad: dp(8)
        padding: dp(15)
        spacing: dp(10)
        Label:
            text: root.text
            font_size: sp(14)
            color: INK
            halign: 'left'
            valign: 'middle'
            text_size: self.size
        Button:
            text: root.next_text
            bold: True
            size_hint: None, None
            size: dp(130), dp(36)
            pos_hint: {'right': 1}
            background_normal: ''
            background_color: BLUE
            on_release: app.controller.next_coach()

<SplashView>:
    canvas.before:
        Color:
            rgba: 0.961, 0.961, 0.961, 1
        Rectangle:
            pos: self.pos
            size: self.size
        Color:
            rgba: 0.867, 0.867, 0.867, 1
        Line:
            circle: self.center_x, self.center_y + dp(20), dp(25)
            width: dp(3)
        Color:
            rgba: RED
        Line:
            circle: self.center_x, self.center_y + dp(20), dp(25), root.angle, root.angle + 90
            width: dp(3)
    Label:
        text: 'LOAD APLIKASI...'
        font_size: sp(15)
        bold: True
        color: RED
        size_hint: None, None
        size: dp(240), dp(30)
        pos_hint: {'center_x': .5, 'center_y': .42}

<RootView>:
    BoxLayout:
        orientation: 'vertical'
        canvas.before:
            Color:
                rgba: 0.961, 0.961, 0.961, 1
            Rectangle:
                pos: self.pos
                size: self.size
        BoxLayout:
            size_hint_y: None
            height: dp(58)
            padding: dp(16), dp(8)
            spacing: dp(14)
            canvas.before:
                Color:
                    rgba: 1, 1, 1, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
                Color:
                    rgba: 0.88, 0.88, 0.88, 1
                Rectangle:
                    pos: self.x, self.y
                    size: self.width, 1
            MenuButton:
                id: btn_menu
                text: 'MENU'
                bold: True
                font_size: sp(14)
                size_hint_x: None
                width: dp(72)
                background_normal: ''
                background_down: ''
                background_color: 0, 0, 0, 0
                color: 0.33, 0.33, 0.33, 1
                on_release: app.menu_pressed(self)
            Label:
                text: 'TIMER MAXDIS'
                font_size: sp(20)
                bold: True
                color: INK
                halign: 'left'
                valign: 'middle'
                text_size: self.size
            RedBtn:
                text: 'TIMER'
                font_size: sp(13)
                size_hint: None, None
                size: dp(72), dp(34)
                pos_hint: {'center_y': .5}
        ScrollView:
            do_scroll_x: False
            BoxLayout:
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                spacing: dp(12)
                AnchorLayout:
                    anchor_x: 'center'
                    size_hint_y: None
                    height: dp(96)
                    padding: dp(20), dp(14)
                    canvas.before:
                        Color:
                            rgba: 1, 1, 1, 1
                        Rectangle:
                            pos: self.pos
                            size: self.size
                    BoxLayout:
                        size_hint: None, 1
                        width: min(root.width - dp(40), dp(400))
                        canvas.before:
                            Color:
                                rgba: 0.878, 0.878, 0.878, 1
                            Rectangle:
                                pos: self.x + dp(40), self.top - dp(19)
                                size: self.width - dp(80), dp(3)
                        StepItem:
                            id: s1
                            num: '1'
                            caption: 'Input'
                            state: 'active'
                            size_hint_x: 1
                        StepItem:
                            id: s2
                            num: '2'
                            caption: 'Proses'
                            size_hint_x: 1
                        StepItem:
                            id: s3
                            num: '3'
                            caption: 'Selesai'
                            size_hint_x: 1
                Panel:
                    bg: 1, 0.976, 0.769, 1
                    border: 0.98, 0.82, 0.08, 1
                    rad: dp(6)
                    orientation: 'vertical'
                    size_hint_y: None
                    height: dp(100)
                    padding: dp(14)
                    spacing: dp(4)
                    Label:
                        text: 'Isi Qty lalu tekan ENTER untuk mulai timer.'
                        font_size: sp(14)
                        bold: True
                        color: INK
                        halign: 'center'
                        text_size: self.size
                        valign: 'middle'
                    Label:
                        text: 'PERHATIAN: REFRESH SAAT TIMER BERJALAN AKAN MERESET LORONG YANG SEDANG DIKERJAKAN.'
                        font_size: sp(13)
                        bold: True
                        color: 1, 0, 0, 1
                        halign: 'center'
                        text_size: self.size
                        valign: 'middle'
                BoxLayout:
                    orientation: 'vertical'
                    size_hint_y: None
                    height: self.minimum_height
                    canvas.before:
                        Color:
                            rgba: 1, 1, 1, 1
                        Rectangle:
                            pos: self.pos
                            size: self.size
                    BoxLayout:
                        size_hint_y: None
                        height: dp(44)
                        padding: dp(15), 0
                        canvas.before:
                            Color:
                                rgba: RED
                            Rectangle:
                                pos: self.pos
                                size: self.size
                        Label:
                            text: 'Detail Lorong'
                            bold: True
                            font_size: sp(14)
                            halign: 'left'
                            valign: 'middle'
                            text_size: self.size
                        Label:
                            text: 'Qty'
                            bold: True
                            font_size: sp(14)
                            size_hint_x: None
                            width: dp(72)
                        Label:
                            text: 'Status'
                            bold: True
                            font_size: sp(14)
                            size_hint_x: None
                            width: dp(40)
                    BoxLayout:
                        id: rows
                        orientation: 'vertical'
                        size_hint_y: None
                        height: self.minimum_height
                RedBtn:
                    text: 'MULAI TIMER (ENTER)'
                    font_size: sp(15)
                    size_hint: None, None
                    size: min(root.width - dp(30), dp(400)), dp(50)
                    pos_hint: {'center_x': .5}
                    on_release: app.start_pressed()
                Widget:
                    size_hint_y: None
                    height: dp(24)
"""


class TimerMaxdisApp(App):
    title = "TIMER MAXDIS"

    def build(self):
        Window.clearcolor = (0.961, 0.961, 0.961, 1)
        if platform in ("win", "linux", "macosx"):
            Window.size = (420, 780)
        if platform == "android":
            Window.softinput_mode = "below_target"      # papan ketik tidak menutup kolom Qty
        Builder.load_string(KV)
        self.root_view = RootView()
        self.services = Services(self.user_data_dir)
        self.controller = Controller(self.root_view, logic.FileStorage(os.path.join(self.user_data_dir, "store")), self.services)
        Window.bind(on_keyboard=self._on_key)
        Clock.schedule_once(lambda _dt: self.controller.init_app(), 0)
        return self.root_view

    def menu_pressed(self, button):
        if getattr(button, "long_fired", False):
            button.long_fired = False                   # tekan lama sudah ditangani: jangan buka menu
            return
        self.controller.menu()

    def start_pressed(self):
        """Tombol tambahan untuk papan ketik tanpa tombol Enter: sama dengan menekan ENTER di kolom aktif."""
        rows = self.root_view.rows
        idx = self.controller.session.current_index
        if 0 <= idx < len(rows):
            self.controller.on_enter(idx, rows[idx].ids.field.text)

    def _on_key(self, _window, key, *_args):
        return bool(key == 27 and self.controller.on_back())

    def on_pause(self):
        return True                                     # wajib di Android: tanpa ini aplikasi ditutup saat di latar belakang

    def on_resume(self):
        self.controller.on_resume()


if __name__ == "__main__":
    TimerMaxdisApp().run()
