/*
 * REFERENSI: logika inti TIMER MAXDIS disalin dari HTML asli (index.html milik pengguna).
 * Hanya baris yang menyentuh DOM / audio / video / service worker yang dibuang atau
 * diganti pengembalian nilai. Rumus, urutan, pembulatan, dan penyimpanan TIDAK diubah.
 * Dipakai oleh gen_golden.js untuk membuat golden.json (kunci jawaban uji Python).
 */
"use strict";

const lorongData = [
    { code: "L01", name: "LORONG 1" }, { code: "L02", name: "LORONG 2" }, { code: "L03", name: "LORONG 3" },
    { code: "L04", name: "LORONG 4" }, { code: "L05", name: "LORONG 5" }, { code: "L06", name: "LORONG 6" }
];
const TIMER_KEY = "timerMaxdisState";
const SESSION_KEY = "timerMaxdisSession";

let currentIndex = 0;
let currentQty = 0;
let currentTotalSeconds = 0;
let timerEndTimestampMs = 0;
let currentTimerStartTimestampMs = 0;
let isTimerRunning = false;
let qtyHistory = lorongData.map(() => null);
let completedLorong = lorongData.map(() => false);
let sessionStartTimestampMs = 0;
let sessionRecords = [];

/* ---- pengganti lingkungan browser ---- */
const _store = new Map();
const localStorage = {
    getItem: k => (_store.has(k) ? _store.get(k) : null),
    setItem: (k, v) => { _store.set(k, String(v)); },
    removeItem: k => { _store.delete(k); }
};
let _navType = "navigate";
const performance = { getEntriesByType: () => [{ type: _navType }] };
let _now = 0;
function nowMs() { return _now; }

/* ---- UTILITY (asli) ---- */
function formatDuration(totalSeconds) {
    totalSeconds = Math.max(0, Math.round(Number(totalSeconds) || 0));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    if (hours > 0) {
        return String(hours).padStart(2, "0") + ":" + String(minutes).padStart(2, "0") + ":" + String(seconds).padStart(2, "0");
    }
    return String(minutes).padStart(2, "0") + ":" + String(seconds).padStart(2, "0");
}

function formatDateTime(timestamp) {
    if (!timestamp) return "-";
    return new Date(timestamp).toLocaleString("id-ID", {
        day: "2-digit", month: "2-digit", year: "numeric",
        hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false
    });
}

function getNavigationType() {
    try {
        const entry = performance.getEntriesByType("navigation")[0];
        if (entry && entry.type) { return entry.type; }
    } catch (error) { }
    return "navigate";
}

function getShift(timestamp) {
    const hour = new Date(timestamp).getHours();
    if (hour >= 2 && hour < 6) { return "SHIFT 3"; }
    if (hour >= 9 && hour < 16) { return "SHIFT 1"; }
    if (hour >= 21 && hour < 24) { return "SHIFT 2"; }
    return "DI LUAR SHIFT";
}

/* ---- TIMER / SESSION STORAGE (asli) ---- */
function saveTimerState() {
    localStorage.setItem(TIMER_KEY, JSON.stringify({
        running: true, index: currentIndex, qty: currentQty, total: currentTotalSeconds,
        end: timerEndTimestampMs, start: currentTimerStartTimestampMs
    }));
}
function clearTimerState() { localStorage.removeItem(TIMER_KEY); }
function saveSessionState() {
    localStorage.setItem(SESSION_KEY, JSON.stringify({
        index: currentIndex, qtyHistory, completedLorong, sessionStartTimestampMs, sessionRecords
    }));
}
function clearSessionState() {
    localStorage.removeItem(SESSION_KEY);
    qtyHistory = lorongData.map(() => null);
    completedLorong = lorongData.map(() => false);
    currentIndex = 0; currentQty = 0; sessionStartTimestampMs = 0; sessionRecords = [];
}
function loadSessionState() {
    try {
        const raw = localStorage.getItem(SESSION_KEY);
        if (!raw) return;
        const state = JSON.parse(raw);
        if (Array.isArray(state.qtyHistory)) {
            qtyHistory = lorongData.map((_, index) => {
                const value = Number(state.qtyHistory[index]);
                return (Number.isFinite(value) && value > 0) ? value : null;
            });
        }
        if (Array.isArray(state.completedLorong)) {
            completedLorong = lorongData.map((_, index) => state.completedLorong[index] === true);
        }
        if (Number.isFinite(Number(state.sessionStartTimestampMs))) {
            sessionStartTimestampMs = Number(state.sessionStartTimestampMs);
        }
        if (Array.isArray(state.sessionRecords)) {
            sessionRecords = state.sessionRecords
                .filter(record => record && Number.isFinite(Number(record.index)) && Number.isFinite(Number(record.qty)) &&
                    Number.isFinite(Number(record.start)) && Number.isFinite(Number(record.finish)))
                .sort((a, b) => Number(a.index) - Number(b.index));
        }
        if (Number.isInteger(Number(state.index)) && Number(state.index) >= 0 && Number(state.index) < lorongData.length) {
            currentIndex = Number(state.index);
        }
    } catch (error) {
        clearSessionState();
    }
}

/* ---- STARTUP RESET (asli) ---- */
function processStartupReset() {
    const navigationType = getNavigationType();
    let activeTimer = null;
    try {
        const raw = localStorage.getItem(TIMER_KEY);
        if (raw) {
            const state = JSON.parse(raw);
            if (state && state.running === true) { activeTimer = state; }
        }
    } catch (error) { activeTimer = null; }

    if (navigationType === "reload" && activeTimer) {
        loadSessionState();
        const index = Number(activeTimer.index);
        if (Number.isInteger(index) && index >= 0 && index < lorongData.length) {
            qtyHistory[index] = null;
            completedLorong[index] = false;
            sessionRecords = sessionRecords.filter(record => Number(record.index) !== index);
            if (index === 0) { sessionStartTimestampMs = 0; sessionRecords = []; }
            saveSessionState();
        }
        clearTimerState();
        return;
    }
    if (navigationType === "reload") { clearSessionState(); clearTimerState(); return; }
    clearSessionState(); clearTimerState();
}

/* ---- START / TICK / FINISH (asli, tanpa DOM) ---- */
function startTimer(qty) {
    isTimerRunning = true;
    currentQty = qty;
    currentTimerStartTimestampMs = nowMs();
    if (currentIndex === 0 && sessionRecords.length === 0) { sessionStartTimestampMs = currentTimerStartTimestampMs; }
    completedLorong[currentIndex] = false;
    currentTotalSeconds = Math.ceil((qty / 12) * 60);
    timerEndTimestampMs = currentTimerStartTimestampMs + (currentTotalSeconds * 1000);
    saveTimerState();
    saveSessionState();
}

function tickInfo() {              // bagian hitung dari updateTimerDisplay()
    const remainingMs = Math.max(0, timerEndTimestampMs - nowMs());
    const seconds = Math.ceil(remainingMs / 1000);
    const minutes = Math.floor(seconds / 60);
    const remaining = seconds % 60;
    const display = `${String(minutes).padStart(2, "0")}:${String(remaining).padStart(2, "0")}`;
    const progress = currentTotalSeconds > 0 ? seconds / currentTotalSeconds : 0;
    const safeProgress = Math.max(0, Math.min(1, progress));
    let message;
    if (seconds <= 10) { message = "Hampir selesai!"; }
    else if (seconds <= 30) { message = "30 detik terakhir."; }
    else if (seconds <= 60) { message = "Tinggal sebentar lagi."; }
    else { message = "Waktu berjalan."; }
    return { display, progressPercent: safeProgress * 100, message, finished: remainingMs <= 0 };
}

function finishTimer() {
    if (!isTimerRunning) { return; }
    isTimerRunning = false;
    clearTimerState();
    timerEndTimestampMs = 0;
    const finishTimestamp = nowMs();
    qtyHistory[currentIndex] = currentQty;
    completedLorong[currentIndex] = true;
    sessionRecords.push({
        index: currentIndex, code: lorongData[currentIndex].code, qty: currentQty,
        start: currentTimerStartTimestampMs, finish: finishTimestamp
    });
    saveSessionState();
}

/* ---- CALCULATION (asli) ---- */
function getOrderedRecords() { return sessionRecords.slice().sort((a, b) => Number(a.index) - Number(b.index)); }
function calculateTotalQty() {
    return qtyHistory.reduce((total, qty) => {
        const value = Number(qty);
        if (Number.isFinite(value) && value > 0) { return total + value; }
        return total;
    }, 0);
}
function calculateWorkSeconds(records) {
    return records.reduce((total, record) => {
        const start = Number(record.start); const finish = Number(record.finish);
        if (finish > start) { return total + (finish - start) / 1000; }
        return total;
    }, 0);
}
function calculateGapSeconds(records) {
    let gap = 0;
    for (let i = 1; i < records.length; i++) {
        const previous = records[i - 1]; const current = records[i];
        const gapMs = Number(current.start) - Number(previous.finish);
        if (gapMs > 0) { gap += gapMs / 1000; }
    }
    return gap;
}
function calculateActualSeconds(records) {
    if (!records.length) { return 0; }
    const firstStart = Number(records[0].start);
    const lastFinish = Number(records[records.length - 1].finish);
    if (!Number.isFinite(firstStart) || !Number.isFinite(lastFinish) || lastFinish < firstStart) { return 0; }
    return (lastFinish - firstStart) / 1000;
}
function calculateTargetSeconds(totalQty) { return (totalQty / 60) * 5 * 60; }
function evaluateTiming(targetSeconds, actualSeconds) {
    if (targetSeconds <= 0) { return { deviation: 0, type: "good", text: "DATA WAKTU BELUM CUKUP" }; }
    const deviation = ((actualSeconds - targetSeconds) / targetSeconds) * 100;
    if (deviation < -10) { return { deviation, type: "fast", text: "DISPLAY TERLALU CEPAT" }; }
    if (deviation <= 10) { return { deviation, type: "good", text: "BAGUS, DISPLAY TEPAT WAKTU" }; }
    return { deviation, type: "slow", text: "DISPLAY TERLALU LAMA" };
}

function showResultPopup() {      // bagian hitung/format dari showResultPopup(); null bila tidak lengkap
    const records = getOrderedRecords();
    if (records.length !== lorongData.length) { return null; }
    const totalQty = calculateTotalQty();
    const workSeconds = calculateWorkSeconds(records);
    const gapSeconds = calculateGapSeconds(records);
    const actualSeconds = calculateActualSeconds(records);
    const targetSeconds = calculateTargetSeconds(totalQty);
    const evaluation = evaluateTiming(targetSeconds, actualSeconds);
    const firstStart = Number(records[0].start);
    const lastFinish = Number(records[records.length - 1].finish);
    return {
        totalQty: totalQty.toLocaleString("id-ID"),
        shift: getShift(firstStart),
        target: formatDuration(targetSeconds),
        work: formatDuration(workSeconds),
        gap: formatDuration(gapSeconds),
        actual: formatDuration(actualSeconds),
        percent: `${evaluation.deviation >= 0 ? "+" : ""}${evaluation.deviation.toFixed(1)}%`,
        finishedAt: formatDateTime(lastFinish),
        statusType: evaluation.type,
        statusText: evaluation.text
    };
}

function finishLorong() {         // bagian logika dari finishLorong(): pengembalian = hasil bila sesi selesai
    clearTimerState();
    currentIndex++;
    if (currentIndex >= lorongData.length) { saveSessionState(); return { result: showResultPopup() }; }
    saveSessionState();
    return { result: null };
}

function resetCompletedSession() { clearSessionState(); clearTimerState(); }

/* ---- COACH: posisi tooltip (asli) ---- */
function coachPos(rect, innerWidth, innerHeight, tipHeight) {
    const width = 260;
    let left = rect.left + rect.width / 2 - width / 2;
    left = Math.max(10, Math.min(left, innerWidth - width - 10));
    let top = rect.bottom + 15;
    if (top + tipHeight > innerHeight - 10) { top = rect.top - tipHeight - 15; }
    return { left, top: Math.max(10, top) };
}

/* ---- antarmuka uji ---- */
function snapshot() {
    return {
        currentIndex, currentQty, qtyHistory, completedLorong, sessionStartTimestampMs, sessionRecords,
        isTimerRunning, currentTotalSeconds, timerEndTimestampMs, currentTimerStartTimestampMs,
        storage: Object.fromEntries(_store)
    };
}
function reset(opts) {
    opts = opts || {};
    _store.clear();
    for (const [k, v] of Object.entries(opts.storage || {})) { _store.set(k, v); }
    _navType = opts.nav || "navigate";
    _now = opts.now || 0;
    currentIndex = 0; currentQty = 0; currentTotalSeconds = 0; timerEndTimestampMs = 0; currentTimerStartTimestampMs = 0;
    isTimerRunning = false;
    qtyHistory = lorongData.map(() => null);
    completedLorong = lorongData.map(() => false);
    sessionStartTimestampMs = 0; sessionRecords = [];
}
module.exports = {
    reset, snapshot, setNow: v => { _now = v; }, setHistory: (q, r) => { qtyHistory = q; sessionRecords = r; },
    formatDuration, formatDateTime, getShift, startTimer, tickInfo, finishTimer, finishLorong, showResultPopup,
    processStartupReset, resetCompletedSession, coachPos, evaluateTiming, calculateTargetSeconds, calculateTotalQty,
    calculateWorkSeconds, calculateGapSeconds, calculateActualSeconds,
    num: x => x.toLocaleString("id-ID"), fixed1: x => x.toFixed(1), ceilDur: q => Math.ceil((q / 12) * 60)
};
