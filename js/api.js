/* ============================================================
   ВСЕ API ПРОЕКТА В ОДНОМ ФАЙЛЕ.
   Сайт обращается к данным только через объект API.
   Каждая функция: заглушка (MOCK) + готовый шаблон реального запроса (REAL).
   Переключение: CFG.USE_MOCK в config.js
   ============================================================ */

/* ---------- MOCK: имитация базы в памяти ---------- */
const DB = { rooms: {} };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const MOCK_PHRASES = ["Привет всем!","Ну давай, попробуй меня рассмешить","Хм, интересно…","Это было мощно","Следующий ход за мной"];
const MOCK_FEELINGS = ["Радость","Азарт","Спокойствие","Удивление","Напряжение","Грусть"];
const pick = arr => arr[Math.random() * arr.length | 0];

/* ---------- REAL: общий помощник для запросов ---------- */
async function http(method, path, body) {
  const res = await fetch(CFG.API_BASE + path, {
    method, headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined
  });
  return res.json();
}

const API = {

  /* Создать комнату. Вход: code. Выход: {ok, code} */
  async createRoom(code) {
    if (!CFG.USE_MOCK) return http("POST", "/rooms", { code });
    await sleep(150); DB.rooms[code] = { players: [] };
    return { ok: true, code };
  },

  /* Подключить игрока. Вход: code, nick. Выход: {ok, error?, playerId?} */
  async joinRoom(code, nick) {
    if (!CFG.USE_MOCK) return http("POST", `/rooms/${code}/join`, { nick });
    await sleep(150);
    const r = DB.rooms[code];
    if (!r) return { ok: false, error: "Комната не найдена" };
    if (r.players.some(p => p.nick === nick)) return { ok: false, error: "Ник занят" };
    const id = "p" + Math.random().toString(36).slice(2, 7);
    r.players.push({ id, nick, score: 0 });
    return { ok: true, playerId: id };
  },

  /* Список игроков. Выход: [{id, nick}] */
  async getPlayers(code) {
    if (!CFG.USE_MOCK) return http("GET", `/rooms/${code}/players`);
    return DB.rooms[code] ? DB.rooms[code].players.map(p => ({ id: p.id, nick: p.nick })) : [];
  },

  /* Ссылка на видеопоток веб-камеры игрока. Выход: строка URL или null */
  getVideoSrc(playerId) {
    if (!CFG.USE_MOCK) return `${CFG.API_BASE}/video/${playerId}`; // TODO: подставьте реальный URL потока
    return null; // null -> показывается плейсхолдер
  },

  /* Начать раунд. Выход: {ok} */
  async startRound(code) {
    if (!CFG.USE_MOCK) return http("POST", `/rooms/${code}/start`);
    await sleep(100); return { ok: true };
  },

  /* Субтитры. Выход: { [playerId]: "текст" } */
  async getSubtitles(code) {
    if (!CFG.USE_MOCK) return http("GET", `/rooms/${code}/subtitles`);
    const o = {}; DB.rooms[code].players.forEach(p => o[p.id] = pick(MOCK_PHRASES)); return o;
  },

  /* Очки (опрос раз в 10 с). Выход: { [playerId]: число } */
  async getScores(code) {
    if (!CFG.USE_MOCK) return http("GET", `/rooms/${code}/scores`);
    const o = {};
    DB.rooms[code].players.forEach(p => { p.score += Math.random() * 40 | 0; o[p.id] = p.score; });
    return o;
  },

  /* «Чувство» (опрос раз в 30 с). Выход: { [playerId]: "текст" } */
  async getFeelings(code) {
    if (!CFG.USE_MOCK) return http("GET", `/rooms/${code}/feelings`);
    const o = {}; DB.rooms[code].players.forEach(p => o[p.id] = pick(MOCK_FEELINGS)); return o;
  },

  /* Завершить раунд (отправить итог). Вход: code, scores. Выход: {ok} */
  async finishRound(code, scores) {
    if (!CFG.USE_MOCK) return http("POST", `/rooms/${code}/finish`, { scores });
    return { ok: true };
  }
};
