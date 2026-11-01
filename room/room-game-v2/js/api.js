/* API-клиент для локального демо и активного WebSocket-сервера. */
const DB = { rooms: {} };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const MOCK_PHRASES = ["Привет всем!","Ну давай, попробуй меня рассмешить","Хм, интересно…","Это было мощно","Следующий ход за мной"];
const MOCK_FEELINGS = ["Радость","Азарт","Спокойствие","Удивление","Напряжение","Грусть"];
const pick = arr => arr[Math.random() * arr.length | 0];
const loadLeaderboard = () => { try { return JSON.parse(localStorage.getItem("allTimeLeaderboard") || "[]"); } catch (e) { return []; } };
const saveLeaderboard = rows => { try { localStorage.setItem("allTimeLeaderboard", JSON.stringify(rows)); } catch (e) {} };
async function http(method, path, body) {
  const res = await fetch(CFG.API_BASE + path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  if (!res.ok) throw new Error("API HTTP " + res.status);
  return res.json();
}
const API = {
  async createRoom(code, admin = false) {
    if (!CFG.USE_MOCK) return http("POST", "/api/rooms/create");
    await sleep(100);
    DB.rooms[code] = { players: [], admin, feeling: pick(MOCK_FEELINGS), feelingAt: Date.now() };
    return { ok: true, code };
  },
  async joinRoom(code, nick) {
    if (!CFG.USE_MOCK) return Session.join(code, nick);
    await sleep(80);
    const r = DB.rooms[code];
    if (!r) return { ok: false, error: "Комната не найдена" };
    if (r.players.some(p => p.nick === nick)) return { ok: false, error: "Ник занят" };
    const id = "p" + Math.random().toString(36).slice(2, 7);
    r.players.push({ id, nick, score: 0 });
    return { ok: true, playerId: id };
  },
  async openAdminRoom(accessCode) {
    if (accessCode !== "000000") return { ok: false, error: "Неверный код доступа" };
    if (!CFG.USE_MOCK) return { ok: false, error: "Админ-комната доступна только в демо-режиме" };
    if (!DB.rooms.ADMIN) await this.createRoom("ADMIN", true);
    return { ok: true, code: "ADMIN" };
  },
  async addTestPlayer(code) {
    if (!CFG.USE_MOCK) return { ok: false, error: "Тестовые игроки доступны только в демо-режиме" };
    const r = DB.rooms[code];
    if (!r || !r.admin) return { ok: false, error: "Тестовые игроки доступны только в админской комнате" };
    const nick = "Тестовый игрок " + (r.players.filter(p => p.isBot).length + 1);
    const id = "bot" + Math.random().toString(36).slice(2, 7);
    r.players.push({ id, nick, score: 0, isBot: true });
    return { ok: true };
  },
  async getPlayers(code) {
    if (!CFG.USE_MOCK) {
      const response = await http("GET", "/api/rooms");
      const room = response && response.rooms ? response.rooms[code] : null;
      return room && room.users ? room.users.map(user => ({ id: user.uid, nick: user.nickname })) : [];
    }
    return DB.rooms[code] ? DB.rooms[code].players.map(p => ({ id: p.id, nick: p.nick })) : [];
  },
  getVideoSrc(playerId) { return CFG.USE_MOCK ? null : Session.videoUrl(playerId); },
  async startRound(code) {
    if (!CFG.USE_MOCK) {
      Session.startRound();
      return { ok: true };
    }
    await sleep(80); return { ok: true };
  },
  async getSubtitles(code, playerId) {
    if (!CFG.USE_MOCK) return Session.textFor(playerId);
    return pick(MOCK_PHRASES);
  },
  async getScores(code) {
    if (!CFG.USE_MOCK) return Session.scores();
    const o = {}; const r = DB.rooms[code];
    if (r) r.players.forEach(p => { p.score += Math.random() * 40 | 0; o[p.id] = p.score; });
    return o;
  },
  // Сервер хранит одно чувство на комнату и рассылает его всем игрокам.
  async getFeelings(code) {
    if (!CFG.USE_MOCK) return Session.feeling();
    const r = DB.rooms[code]; if (!r) return {};
    if (Date.now() - r.feelingAt >= CFG.FEEL_MS) { r.feeling = pick(MOCK_FEELINGS); r.feelingAt = Date.now(); }
    return Object.fromEntries(r.players.map(p => [p.id, r.feeling]));
  },
  async getLeaderboard() {
    if (!CFG.USE_MOCK) return http("GET", "/api/leaderboard");
    return loadLeaderboard().sort((a,b) => b.score - a.score);
  },
  async getTopWinner() {
    return (await this.getLeaderboard())[0] || null;
  },
  async finishRound(code, scores) {
    if (!CFG.USE_MOCK) {
      const result = Session.result();
      return result
        ? { ok: true, rank: null, totalScore: result.your_score, winner: result.winner, winnerScore: result.winner_score }
        : { ok: true, rank: null };
    }
    const r = DB.rooms[code]; if (!r) return { ok: true, rank: null };
    const rows = loadLeaderboard();
    r.players.forEach(p => {
      const old = rows.find(x => x.nick === p.nick);
      if (old) old.score += scores[p.id] || 0;
      else rows.push({ nick: p.nick, score: scores[p.id] || 0 });
    });
    rows.sort((a,b) => b.score - a.score);
    saveLeaderboard(rows);
    const winner = [...r.players].sort((a,b) => (scores[b.id]||0) - (scores[a.id]||0))[0];
    const rank = winner ? rows.findIndex(x => x.nick === winner.nick) + 1 : null;
    return { ok: true, rank, totalScore: winner ? rows[rank-1].score : 0 };
  }
};
