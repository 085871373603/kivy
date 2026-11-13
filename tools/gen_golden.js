// Hasilkan golden.json dari referensi JS asli.  Jalankan:  TZ=Asia/Jakarta node tools/gen_golden.js > golden.json
"use strict";
const R = require("./reference.js");
let s = 123456789;
function rnd() { s |= 0; s = (s + 0x6D2B79F5) | 0; let t = Math.imul(s ^ (s >>> 15), 1 | s); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }
const ri = (a, b) => a + Math.floor(rnd() * (b - a + 1));
const pick = a => a[ri(0, a.length - 1)];
const G = {};

// 1. formatDuration
const durs = [0, -5, 0.4, 0.49999, 0.5, 1.5, 2.5, 59.5, 59.4, 60, 61, 599.5, 3599.4, 3599.5, 3600, 3661, 7325.5, 86399.5, 360000, 1e6, NaN, Infinity === 1 ? 0 : 12.345];
for (let i = 0; i < 300; i++) durs.push(rnd() * pick([60, 600, 4000, 90000]));
G.format_duration = durs.map(x => [Number.isNaN(x) ? "NaN" : x, R.formatDuration(x)]);

// 2. shift + 3. datetime (zona waktu proses = Asia/Jakarta)
const base = Date.UTC(2026, 0, 1);
G.shift = []; G.datetime = [[0, R.formatDateTime(0)]];
for (let h = 0; h < 24; h++) for (const m of [0, 1, 59]) { const t = base + (h * 60 + m) * 60000 - 7 * 3600000; G.shift.push([t, R.getShift(t)]); G.datetime.push([t, R.formatDateTime(t)]); }
for (let i = 0; i < 300; i++) { const t = Date.UTC(2024, 0, 1) + Math.floor(rnd() * 3 * 365 * 86400000); G.datetime.push([t, R.formatDateTime(t)]); G.shift.push([t, R.getShift(t)]); }

// 4. angka id-ID dan 5. toFixed(1)
const nums = [0, 1, 12, 999, 1000, 1234, 12345.6, 1234567.891, 0.5, 0.0005, 0.0015, 2.0005, 100000, 1e9, 12.3456, 7.1235, 5.5555, 1e-7];
for (let i = 0; i < 400; i++) nums.push(pick([ri(0, 5000), ri(0, 90000) / 7, ri(0, 100000) / 1000, ri(0, 1e7) / 13]));
for (let i = 0; i < 700; i++) nums.push(pick([(ri(0, 99999) + 0.5) / 1000, ri(0, 1e6) / 1e4, ri(0, 1e5) / 1e5, (ri(0, 9999) + 0.5) / 10000, ri(1, 99) + 0.0005, ri(1, 99) + 0.9995]));
G.number_id = nums.map(x => [x, R.num(x)]);
const fx = [0, -0, 0.25, -0.25, 0.05, -0.05, 0.15, 0.35, 1.45, 2.675, -0.04, -0.0001, 9.95, 10.05, 99.95, -99.95, 0.1 + 0.2, 100, -10, 10.0000001];
for (let i = 0; i < 500; i++) fx.push((rnd() - 0.5) * pick([1, 10, 100, 1000]));
G.fixed1 = fx.map(x => [x, R.fixed1(x)]);

// 6. durasi timer = ceil((qty/12)*60)
const qs = [];
for (let q = 1; q <= 400; q++) qs.push(q);
for (let i = 0; i < 400; i++) qs.push(pick([ri(1, 5000), ri(1, 90000) / 100, ri(1, 3000) / 7, 0.1, 0.5, 11.9999999, 12.0000001]));
G.ceil_duration = qs.map(q => [q, R.ceilDur(q)]);

// 7. tick: tampilan, progres, pesan
G.tick = [];
for (let i = 0; i < 600; i++) {
    const qty = pick([ri(1, 300), ri(1, 5000) / 10, 1, 12]); R.reset({ now: 5000 }); R.startTimer(qty);
    const total = R.snapshot().currentTotalSeconds * 1000;
    const el = pick([0, 1, total, total + 1, total - 1, ri(0, total + 5000), Math.max(0, total - 10000), Math.max(0, total - 10001), Math.max(0, total - 30000), Math.max(0, total - 60000), Math.max(0, total - 60001), Math.max(0, total - 9999), 999, 1000, 1001]);
    R.setNow(5000 + el); G.tick.push([qty, el, R.tickInfo()]);
}

// 8. evaluateTiming + batas
G.evaluate = [];
const tg = [0, -3, 1, 300, 777.5, 5400, 1e5];
for (const t of tg) for (const f of [0, 0.5, 0.8999, 0.9, 0.90001, 1, 1.0999, 1.1, 1.10001, 1.5, 3]) G.evaluate.push([t, t * f, R.evaluateTiming(t, t * f)]);
for (let i = 0; i < 300; i++) { const t = rnd() * 20000; const a = rnd() * 40000; G.evaluate.push([t, a, R.evaluateTiming(t, a)]); }

// 9. alur sesi penuh (mulai -> selesai -> lorong berikutnya) -> hasil + status + penyimpanan
G.sessions = [];
for (let n = 0; n < 220; n++) {
    const steps = []; let t = Date.UTC(2026, ri(0, 11), ri(1, 28), ri(0, 23), ri(0, 59), ri(0, 59), ri(0, 999)) + ri(0, 999);
    const count = n % 11 === 0 ? ri(1, 5) : 6;                       // sebagian sesi tidak lengkap
    for (let i = 0; i < count; i++) {
        const qty = pick([ri(1, 400), ri(1, 4000) / 10, 12, 60, 1]);
        const start = t + pick([0, 0, ri(0, 60000), ri(0, 600000)]); const total = Math.ceil((qty / 12) * 60) * 1000;
        const finish = start + total + pick([0, 0, ri(0, 3000)]);
        steps.push({ qty, start, finish }); t = finish;
    }
    // sebagian sesi: target dibuat dekat batas +-10% dengan mengubah celah
    R.reset({ now: 0 }); const log = []; let result = null;
    for (const st of steps) {
        R.setNow(st.start); R.startTimer(st.qty); const mid = R.snapshot();
        R.setNow(st.finish); R.finishTimer(); const fin = R.snapshot(); const r = R.finishLorong(); result = r.result;
        log.push({ afterStart: { storage: mid.storage, total: mid.currentTotalSeconds, end: mid.timerEndTimestampMs }, afterFinish: { storage: fin.storage }, result });
    }
    G.sessions.push({ steps, log: n < 25 ? log : [], final: R.snapshot(), result });
}
// sesi dengan rasio waktu tepat di batas -10% / +10% dan sesi dengan jeda sangat besar
for (const ratio of [0.9, 0.8999, 1.0, 1.1, 1.1001, 0.5, 2.5]) {
    const qty = 60; const steps = []; let t = Date.UTC(2026, 4, 5, 10, 0, 0);
    const targetMs = (qty * 6 / 60) * 5 * 60 * 1000;                     // total qty 360 -> target 30 menit
    const per = Math.ceil((qty / 12) * 60) * 1000;
    const wantActual = targetMs * ratio; const extra = Math.max(0, wantActual - per * 6) / 5;
    for (let i = 0; i < 6; i++) { const start = t; const finish = start + per; steps.push({ qty, start, finish }); t = finish + extra; }
    R.reset({ now: 0 }); let result = null;
    for (const st of steps) { R.setNow(st.start); R.startTimer(st.qty); R.setNow(st.finish); R.finishTimer(); result = R.finishLorong().result; }
    G.sessions.push({ steps, log: [], final: R.snapshot(), result });
}

// 10. reset saat start (processStartupReset) untuk semua kombinasi
function playedStorage(k, withDecimal) {
    R.reset({ now: 0 }); let t = Date.UTC(2026, 2, 3, 9, 0, 0);
    for (let i = 0; i < k; i++) { const qty = withDecimal ? 12.5 + i : 10 + i; R.setNow(t); R.startTimer(qty); t += 90000; R.setNow(t); R.finishTimer(); R.finishLorong(); t += 5000; }
    return R.snapshot().storage;
}
const timers = [null, "{\"running\":true,\"index\":0}", "{\"running\":true,\"index\":1}", "{\"running\":true,\"index\":3,\"qty\":5}", "{\"running\":true,\"index\":5}",
    "{\"running\":false,\"index\":2}", "{bad json", "{\"running\":true,\"index\":9}", "{\"running\":true,\"index\":\"2\"}", "{\"running\":true,\"index\":-1}", "{\"running\":true,\"index\":1.5}", "null", "{\"running\":true}", "{\"running\":\"true\",\"index\":2}"];
const sessions = [null, playedStorage(1)["timerMaxdisSession"], playedStorage(3)["timerMaxdisSession"], playedStorage(5, true)["timerMaxdisSession"], "{bad", "{}", "null",
    JSON.stringify({ index: 4, qtyHistory: [5, "7", -1, null, "abc", 0], completedLorong: [true, "true", 1, false, true, null], sessionStartTimestampMs: "123", sessionRecords: [{ index: 2, qty: 3, start: 1, finish: 2 }, { index: 0, qty: "4", start: 5, finish: 6 }, null, { index: "x", qty: 1, start: 1, finish: 1 }, { index: 1, qty: 1, start: 1 }] }),
    JSON.stringify({ index: 99, qtyHistory: "salah", completedLorong: {}, sessionStartTimestampMs: null, sessionRecords: "x" }),
    JSON.stringify({ index: 2, qtyHistory: [1, 2, 3, 4, 5, 6, 7], completedLorong: [true, true, true, true, true, true, true], sessionStartTimestampMs: 5, sessionRecords: [{ index: 0, qty: 1, start: 1, finish: 2 }, { index: 1, qty: 1, start: 3, finish: 4 }] })];
G.startup = [];
for (const nav of ["navigate", "reload", "back_forward"]) for (const tm of timers) for (const ss of sessions) {
    const storage = {}; if (tm !== null) storage["timerMaxdisState"] = tm; if (ss !== null) storage["timerMaxdisSession"] = ss;
    R.reset({ nav, storage }); R.processStartupReset(); const snap = R.snapshot();
    G.startup.push({ nav, storage, after: { currentIndex: snap.currentIndex, qtyHistory: snap.qtyHistory, completedLorong: snap.completedLorong, sessionStartTimestampMs: snap.sessionStartTimestampMs, sessionRecords: snap.sessionRecords, storage: snap.storage } });
}

// 11. posisi tooltip tutorial
G.coach = [];
for (let i = 0; i < 400; i++) {
    const iw = pick([320, 360, 393, 412, 480]), ih = pick([560, 640, 740, 800, 915]);
    const w = ri(40, iw - 20), h = ri(20, 80), left = ri(-20, iw), top = ri(0, ih), tip = pick([90, 100, 117]);
    const rect = { left, top, width: w, height: h, bottom: top + h };
    G.coach.push([rect, iw, ih, tip, R.coachPos(rect, iw, ih, tip)]);
}
process.stdout.write(JSON.stringify(G));
