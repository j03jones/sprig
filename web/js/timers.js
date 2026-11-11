// Kitchen timers. Steps that mention a time ("simmer 15 minutes") get a button that starts a countdown.
// Timers keep running while you move around the app and survive a reload (they store their end time).
import { buzz } from './ui.js';

const KEY = 'sprig.timers';
const WORDS = { one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10, twelve: 12, fifteen: 15, twenty: 20, thirty: 30, forty: 40, sixty: 60, 'a half': 0.5, half: 0.5 };
const NUM = '\\d+(?:\\.\\d+)?|' + Object.keys(WORDS).join('|');
const TIME = new RegExp(`\\b(${NUM})(?:\\s*(?:-|–|to)\\s*(${NUM}))?\\s*(hours?|hrs?|minutes?|mins?|seconds?|secs?)\\b`, 'gi');
const val = (x) => (x == null ? null : (WORDS[x.toLowerCase()] ?? parseFloat(x)));
let timers = [];            // { id, label, end, done }
let box = null;
let ticker = null;
let audio = null;

/** Finds the times in a step: [{ label: '10–12 min', seconds: 600 }] (uses the shorter time of a range). */
export function findTimes(text) {
  const out = []; const seen = new Set();
  for (const m of String(text).matchAll(TIME)) {
    const lo = val(m[1]);
    const unit = m[3].toLowerCase();
    const mult = unit.startsWith('h') ? 3600 : unit.startsWith('m') ? 60 : 1;
    const seconds = Math.round(lo * mult);
    if (seconds < 5 || seconds > 24 * 3600) continue;
    const short = unit.startsWith('h') ? 'hr' : unit.startsWith('m') ? 'min' : 'sec';
    const label = `${m[1]}${m[2] ? `–${m[2]}` : ''} ${short}`;
    if (seen.has(label)) continue;
    seen.add(label); out.push({ label, seconds });
    if (out.length === 3) break;
  }
  return out;
}

const fmt = (s) => {
  s = Math.max(0, Math.ceil(s));
  const h = Math.floor(s / 3600); const m = Math.floor((s % 3600) / 60); const x = s % 60;
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(x).padStart(2, '0')}` : `${m}:${String(x).padStart(2, '0')}`;
};
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(timers.filter((t) => !t.done))); } catch { /* ignore */ } };

function beep() {
  try {
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    for (let i = 0; i < 3; i++) {
      const o = audio.createOscillator(); const g = audio.createGain();
      o.type = 'sine'; o.frequency.value = 880;
      o.connect(g); g.connect(audio.destination);
      const t = audio.currentTime + i * 0.35;
      g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.25, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.28);
      o.start(t); o.stop(t + 0.3);
    }
  } catch { /* no sound available */ }
}

function ensureBox() {
  if (box) return box;
  box = document.createElement('div');
  box.id = 'timers';
  box.setAttribute('role', 'region');
  box.setAttribute('aria-label', 'Timers');
  document.body.append(box);
  return box;
}

function render() {
  ensureBox();
  box.replaceChildren(...timers.map((t) => {
    const el = document.createElement('div');
    el.className = `timer${t.done ? ' done' : ''}`;
    el.dataset.id = t.id;
    const left = Math.max(0, (t.end - Date.now()) / 1000);
    el.innerHTML = '<span class="tl"></span><b class="tt"></b><button type="button" class="plus" aria-label="Add one minute">+1</button><button type="button" class="x" aria-label="Dismiss timer">×</button>';
    el.querySelector('.tl').textContent = t.label;
    el.querySelector('.tt').textContent = t.done ? 'Time!' : fmt(left);
    el.querySelector('.plus').onclick = () => { t.end += 60000; if (t.done) { t.done = false; } save(); render(); start(); };
    el.querySelector('.x').onclick = () => { timers = timers.filter((x) => x !== t); save(); render(); };
    return el;
  }));
  box.hidden = timers.length === 0;
}

function tickAll() {
  let changed = false;
  for (const t of timers) {
    const left = (t.end - Date.now()) / 1000;
    const el = box.querySelector(`[data-id="${t.id}"] .tt`);
    if (!t.done && left <= 0) {
      t.done = true; changed = true;
      buzz([200, 100, 200, 100, 400]); beep();
      document.dispatchEvent(new CustomEvent('timerdone', { detail: t }));
    } else if (el && !t.done) el.textContent = fmt(left);
  }
  if (changed) { save(); render(); }
  if (!timers.some((t) => !t.done)) { clearInterval(ticker); ticker = null; }
}
function start() { if (!ticker) ticker = setInterval(tickAll, 500); }

export function startTimer(label, seconds) {
  try { audio = audio || new (window.AudioContext || window.webkitAudioContext)(); audio.resume?.(); } catch { /* ignore */ }
  timers.push({ id: Math.random().toString(36).slice(2), label, end: Date.now() + seconds * 1000, done: false });
  save(); render(); start(); buzz(15);
}

/** Brings back timers that were running when the page was closed. */
export function restoreTimers() {
  try { timers = JSON.parse(localStorage.getItem(KEY) || '[]').filter((t) => t && t.end); } catch { timers = []; }
  timers.forEach((t) => { t.done = t.end <= Date.now(); });
  if (timers.length) { render(); start(); }
}

/** Buttons for the times mentioned in `text`; null when there are none. */
export function timerChips(text) {
  const times = findTimes(text);
  if (!times.length) return null;
  const row = document.createElement('div');
  row.className = 'timerchips';
  for (const { label, seconds } of times) {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'tchip';
    b.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="13.5" r="7"/><path d="M12 10v3.8l2.4 1.4M9.5 3h5M12 3v3.5"/></svg>';
    b.append(`Start ${label} timer`);
    b.addEventListener('click', () => startTimer(label, seconds));
    row.append(b);
  }
  return row;
}
