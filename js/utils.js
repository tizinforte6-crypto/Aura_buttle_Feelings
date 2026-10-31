/* Общие утилиты и состояние */
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;" }[c]));
const rand = () => String(Math.floor(100000 + Math.random() * 900000));

let S = { code: null, admin: false, players: [], playing: false, scores: {}, feel: {}, sub: {}, timers: [], left: 0 };

function show(id) { ["s-title", "s-room"].forEach(x => $(x).classList.toggle("hidden", x !== id)); }
function clearTimers() { S.timers.forEach(clearInterval); S.timers = []; }
