/* Общие утилиты и состояние */
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;" }[c]));
const rand = () => String(Math.floor(100000 + Math.random() * 900000));

// me — id текущего игрока (нужен, чтобы показывать ему только его субтитры)
let S = { code: null, admin: false, me: null, players: [], playing: false, scores: {}, feel: {}, currentFeeling: null, mySub: "", timers: [], left: 0 };

// show(id) — переход между экранами, см. js/menu/nav.js
function clearTimers() { S.timers.forEach(clearInterval); S.timers = []; }
